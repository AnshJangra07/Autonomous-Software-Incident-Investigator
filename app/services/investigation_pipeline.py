import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import git
from git.exc import BadName, BadObject, GitError
from pydantic import ValidationError

from app.schemas import (
    GitHistoryEntry,
    InvestigationReport,
    SourceEvidence,
    SourceFunctionEvidence,
)
from app.services.source_code_analyzer import (
    MAX_ALLOWED_RESULTS,
    search_source_code,
    extract_keywords,
)
from app.services.git_diff_analyzer import get_commit_diff
from app.services.diff_change_analyzer import extract_changed_lines
from app.services.git_history_analyzer import (
    MAX_ALLOWED_COMMITS,
    get_file_commit_history,
)
from app.services.historical_ast_analyzer import analyze_historical_functions
from app.services.git_source_reader import get_file_content_at_commit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def _validate_source_evidence_results(results: object) -> list[dict]:
    """Validate source evidence records, retaining valid entries."""
    if not isinstance(results, list):
        raise TypeError("search_source_code must return a list")

    validated_results = []
    for index, result in enumerate(results):
        try:
            validated_result = SourceEvidence.model_validate(result)
        except ValidationError:
            logger.warning(
                "Ignoring malformed source evidence record at index %d",
                index,
            )
            continue
        validated_results.append(
            validated_result.model_dump(
                mode="python",
                exclude_unset=True,
            )
        )

    return validated_results


def _validate_git_history_results(
    file_path: str,
    results: object,
) -> list[dict]:
    """Validate one file's history while retaining valid commit records."""
    if not isinstance(results, list):
        logger.warning(
            "Git history for %s returned a non-list result; ignoring it",
            file_path,
        )
        return []

    validated_results = []
    for index, result in enumerate(results):
        try:
            validated_result = GitHistoryEntry.model_validate(result)
        except ValidationError:
            logger.warning(
                "Ignoring malformed Git history entry %d for %s",
                index,
                file_path,
            )
            continue
        validated_results.append(
            validated_result.model_dump(
                mode="python",
                exclude_unset=True,
            )
        )

    return validated_results


def _empty_change_evidence(
    file_path: str,
    commit_hash: str,
    status: Literal["available", "no_diff", "unavailable", "invalid_diff"],
    error_reason: str | None = None,
) -> dict:
    """Build change evidence when no usable changed lines are available."""
    evidence = {
        "file_path": file_path,
        "commit_hash": commit_hash,
        "added_lines": [],
        "deleted_lines": [],
        "overlaps_suspicious_source_evidence": False,
        "source_evidence_overlap_status": "unavailable",
        "added_lines_overlap_historical_function": False,
        "matching_function_names": [],
        "status": status,
        "note": (
            "Line overlap is supporting evidence only and does not prove "
            "causality."
        ),
    }
    if error_reason is not None:
        evidence["error_reason"] = error_reason
    return evidence


def _analyze_commit_changes(
    file_path: str,
    commit_hash: str,
    source_evidence: list[dict],
) -> dict:
    """Correlate commit changes with evidence and historical functions."""
    try:
        diff_result = get_commit_diff(commit_hash, file_path)
    except (BadName, BadObject, GitError, OSError):
        change_evidence = _empty_change_evidence(
            file_path,
            commit_hash,
            "unavailable",
            "Git diff could not be retrieved.",
        )
    else:
        change_evidence = _parse_commit_diff(
            file_path,
            commit_hash,
            diff_result,
        )

    added_lines = change_evidence["added_lines"]
    deleted_lines = change_evidence["deleted_lines"]

    historical_functions, historical_status, historical_error = (
        _get_historical_functions(commit_hash, file_path)
    )
    added_matches, added_function_names = _match_lines_to_functions(
        added_lines,
        historical_functions,
    )

    deleted_functions = []
    deleted_status = "not_required"
    deleted_error = None
    if deleted_lines:
        parent_commit_hash = _get_parent_commit_hash(commit_hash)
        if parent_commit_hash is None:
            deleted_status = "unavailable"
            deleted_error = (
                "Parent commit is unavailable for deleted-line analysis."
            )
        else:
            deleted_functions, deleted_status, deleted_error = (
                _get_historical_functions(parent_commit_hash, file_path)
            )

    deleted_matches, deleted_function_names = _match_lines_to_functions(
        deleted_lines,
        deleted_functions,
    )

    added_line_numbers = {
        line["line_number"]
        for line in added_lines
    }
    suspicious_line_numbers = {
        evidence.get("line_number")
        for evidence in source_evidence
        if evidence.get("file") == file_path
    }
    source_evidence_overlap_available = _is_current_head_commit(
        commit_hash,
        file_path,
    )

    change_evidence.update({
        "overlaps_suspicious_source_evidence": bool(
            source_evidence_overlap_available
            and added_line_numbers.intersection(suspicious_line_numbers)
        ),
        "source_evidence_overlap_status": (
            "available" if source_evidence_overlap_available else "unavailable"
        ),
        "added_lines_overlap_historical_function": bool(added_function_names),
        "matching_function_names": sorted(
            added_function_names.union(deleted_function_names)
        ),
        "matching_added_function_names": sorted(added_function_names),
        "matching_deleted_function_names": sorted(deleted_function_names),
        "added_line_function_matches": added_matches,
        "deleted_line_function_matches": deleted_matches,
        "historical_ast_status": historical_status,
        "deleted_historical_ast_status": deleted_status,
    })
    if historical_error is not None:
        change_evidence["historical_ast_error_reason"] = historical_error
    if not source_evidence_overlap_available:
        change_evidence["source_evidence_overlap_error_reason"] = (
            "Source evidence is from the current working tree and does not "
            "match this commit."
        )
    if deleted_error is not None:
        change_evidence["deleted_historical_ast_error_reason"] = deleted_error

    return change_evidence


def _is_current_head_commit(commit_hash: str, file_path: str) -> bool:
    """Check that the commit is HEAD and its working file matches HEAD."""
    if not isinstance(commit_hash, str) or not isinstance(file_path, str):
        return False

    requested_path = Path(file_path)
    if (
        requested_path.is_absolute()
        or ".." in requested_path.parts
        or not requested_path.parts
        or requested_path.parts[0] != "app"
        or requested_path.suffix != ".py"
    ):
        return False

    try:
        project_root = Path(PROJECT_ROOT).resolve()
        working_file = project_root / requested_path
        resolved_file = working_file.resolve()
        resolved_file.relative_to(project_root)

        repository = git.Repo(
            project_root,
            search_parent_directories=False,
        )
        candidate_commit = repository.commit(commit_hash)
        head_commit = repository.head.commit
        if candidate_commit.hexsha != head_commit.hexsha:
            return False

        source_result = get_file_content_at_commit(
            head_commit.hexsha,
            requested_path.as_posix(),
        )
        if (
            not isinstance(source_result, dict)
            or source_result.get("status") != "available"
            or not isinstance(source_result.get("content"), str)
            or not working_file.is_file()
        ):
            return False

        if (
            working_file.read_bytes()
            != source_result["content"].encode("utf-8")
        ):
            return False

        repository.git.diff(
            "--quiet",
            head_commit.hexsha,
            "--",
            requested_path.as_posix(),
        )
        return True
    except (BadName, BadObject, GitError, OSError, UnicodeError, ValueError):
        return False


def _parse_commit_diff(
    file_path: str,
    commit_hash: str,
    diff_result: object,
) -> dict:
    """Convert a diff-service result into structured changed-line evidence."""
    if not isinstance(diff_result, dict):
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "unavailable",
            "Git diff result was missing or unusable.",
        )

    if "diff_found" not in diff_result:
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "unavailable",
            "Git diff result did not include a status.",
        )

    if not isinstance(diff_result["diff_found"], bool):
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "unavailable",
            "Git diff result had an invalid status.",
        )

    if "patch" not in diff_result:
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "unavailable",
            "Git diff result did not include patch data.",
        )

    patch = diff_result["patch"]
    if not isinstance(patch, str):
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "invalid_diff",
            "Git patch data was not text.",
        )

    if diff_result["diff_found"] is False:
        if patch:
            return _empty_change_evidence(
                file_path,
                commit_hash,
                "invalid_diff",
                "Git diff result status did not match its patch data.",
            )
        return _empty_change_evidence(file_path, commit_hash, "no_diff")

    if not patch:
        return _empty_change_evidence(file_path, commit_hash, "no_diff")

    try:
        changes = extract_changed_lines(patch)
    except (TypeError, ValueError):
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "invalid_diff",
            "Git patch could not be parsed.",
        )

    change_evidence = _empty_change_evidence(
        file_path,
        commit_hash,
        (
            "available"
            if changes["added_lines"] or changes["deleted_lines"]
            else "no_diff"
        ),
    )
    change_evidence["added_lines"] = changes["added_lines"]
    change_evidence["deleted_lines"] = changes["deleted_lines"]
    return change_evidence


def _get_historical_functions(
    commit_hash: str,
    file_path: str,
) -> tuple[list[dict], str, str | None]:
    """Return historical functions and a safe AST status/reason."""
    result = analyze_historical_functions(commit_hash, file_path)
    if not isinstance(result, dict):
        return [], "unavailable", "Historical AST result is unavailable."

    status = result.get("status")
    if status != "available":
        if not isinstance(status, str) or status not in {
            "not_found",
            "unavailable",
            "invalid_input",
            "invalid_source",
        }:
            status = "unavailable"
        reason = result.get("error_reason")
        if not isinstance(reason, str) or not reason:
            reason = "Historical AST data is unavailable."
        return [], status, reason

    functions = result.get("functions")
    if not isinstance(functions, list):
        return [], "unavailable", "Historical function data is unavailable."

    validated_functions = []
    malformed_function_count = 0
    for index, function in enumerate(functions):
        try:
            validated_function = SourceFunctionEvidence.model_validate(
                function
            )
        except ValidationError:
            malformed_function_count += 1
            logger.warning(
                "Ignoring malformed historical function %d for %s",
                index,
                file_path,
            )
            continue
        validated_functions.append(
            validated_function.model_dump(
                mode="python",
                exclude_unset=True,
            )
        )

    if malformed_function_count and not validated_functions:
        return [], "unavailable", "Historical function data is malformed."
    if malformed_function_count:
        return (
            validated_functions,
            "available",
            "Some historical function data was malformed and ignored.",
        )
    return validated_functions, "available", None


def _match_lines_to_functions(
    changed_lines: list[dict],
    functions: list[dict],
) -> tuple[list[dict], set[str]]:
    """Match changed line numbers to all containing historical functions."""
    line_matches = []
    matching_names = set()

    for changed_line in changed_lines:
        line_number = changed_line["line_number"]
        function_names = {
            function["function_name"]
            for function in functions
            if isinstance(function, dict)
            and isinstance(function.get("function_name"), str)
            and isinstance(function.get("start_line"), int)
            and isinstance(function.get("end_line"), int)
            and function["start_line"] <= line_number <= function["end_line"]
        }
        sorted_names = sorted(function_names)
        matching_names.update(sorted_names)
        line_matches.append({
            "line_number": line_number,
            "function_names": sorted_names,
        })

    return line_matches, matching_names


def _get_parent_commit_hash(commit_hash: str) -> str | None:
    """Get the first parent used as the old-file coordinate space in diffs."""
    try:
        repository = git.Repo(
            PROJECT_ROOT,
            search_parent_directories=False,
        )
        commit = repository.commit(commit_hash)
    except (BadName, BadObject, GitError, OSError):
        return None

    if not commit.parents:
        return None
    return commit.parents[0].hexsha


def _is_missing_source_file_error(
    file_path: str,
    error: ValueError,
) -> bool:
    """Identify the history service's expected missing-file validation error."""
    if str(error) != "Only existing Python files inside app/ are allowed":
        return False
    if not isinstance(file_path, str):
        return False

    requested_path = Path(file_path)
    if (
        requested_path.is_absolute()
        or ".." in requested_path.parts
        or not requested_path.parts
        or requested_path.parts[0] != "app"
        or requested_path.suffix != ".py"
    ):
        return False

    try:
        project_root = Path(PROJECT_ROOT).resolve()
        resolved_path = (project_root / requested_path).resolve()
        resolved_path.relative_to(project_root)
    except (OSError, RuntimeError, ValueError):
        return False

    return not resolved_path.is_file()


def investigate_incident(
    incident: dict,
    max_source_results: int = 10,
    max_commits_per_file: int = 5,
) -> dict:
    """
    Coordinate source-code and Git-history investigation.

    Correlates incident keywords with Git commit messages.
    Returns evidence, not a confirmed root-cause diagnosis.
    """

    if not isinstance(incident, dict):
        raise TypeError("incident must be a dictionary")

    if (
        isinstance(max_source_results, bool)
        or not isinstance(max_source_results, int)
    ):
        raise TypeError("max_source_results must be an integer")

    if max_source_results < 1:
        raise ValueError("max_source_results must be greater than zero")

    if max_source_results > MAX_ALLOWED_RESULTS:
        raise ValueError(
            f"max_source_results must not exceed {MAX_ALLOWED_RESULTS}"
        )

    if (
        isinstance(max_commits_per_file, bool)
        or not isinstance(max_commits_per_file, int)
    ):
        raise TypeError("max_commits_per_file must be an integer")

    if max_commits_per_file < 1:
        raise ValueError("max_commits_per_file must be greater than zero")

    if max_commits_per_file > MAX_ALLOWED_COMMITS:
        raise ValueError(
            f"max_commits_per_file must not exceed {MAX_ALLOWED_COMMITS}"
        )

    # Stage 1: Find relevant source-code locations.
    source_evidence = _validate_source_evidence_results(
        search_source_code(
            incident,
            max_results=max_source_results,
        )
    )

    # Stage 2: Retrieve Git history for each unique source file.
    git_history = {}

    source_files = sorted({
        result["file"]
        for result in source_evidence
    })

    for file_path in source_files:
        try:
            history_results = get_file_commit_history(
                file_path,
                max_commits=max_commits_per_file,
            )
        except ValueError as error:
            if not _is_missing_source_file_error(file_path, error):
                raise
            history_results = []
        git_history[file_path] = _validate_git_history_results(
            file_path,
            history_results,
        )

    # Stage 3: Rank commits using multiple evidence signals.
    incident_text = " ".join(
        str(incident.get(field, ""))
        for field in ("failure_type", "message", "endpoint")
    )

    incident_keywords = set(extract_keywords(incident_text))

    # Find the strongest source-code relevance score for each file.
    source_relevance_by_file = {}

    for result in source_evidence:
        file_path = result["file"]
        score = result.get("relevance_score", 0)

        source_relevance_by_file[file_path] = max(
            source_relevance_by_file.get(file_path, 0),
            score,
        )

    potentially_relevant_commits = []

    for file_path, commits in git_history.items():
        source_score = source_relevance_by_file.get(file_path, 0)

        # Normalize source relevance to a 0-1 range.
        normalized_source_score = min(source_score / 10, 1.0)

        for commit in commits:
            commit_keywords = set(
                extract_keywords(commit.get("message", ""))
            )

            matching_keywords = sorted(
                incident_keywords.intersection(commit_keywords)
            )

            if not matching_keywords:
                continue

            keyword_score = min(
                len(matching_keywords) / max(len(incident_keywords), 1),
                1.0,
            )

            recency_score = calculate_recency_score(
                commit.get("date", "")
            )

            final_score = (
                keyword_score * 0.5
                + normalized_source_score * 0.3
                + recency_score * 0.2
            )

            potentially_relevant_commits.append({
                "file": file_path,
                "commit_hash": commit["commit_hash"],
                "message": commit["message"],
                "matching_keywords": matching_keywords,
                "keyword_score": round(keyword_score, 4),
                "source_relevance_score": round(
                    normalized_source_score, 4
                ),
                "recency_score": recency_score,
                "relevance_score": round(final_score, 4),
                "change_evidence": _analyze_commit_changes(
                    file_path,
                    commit["commit_hash"],
                    source_evidence,
                ),
            })

    # Highest-ranked commits first.
    potentially_relevant_commits.sort(
        key=lambda item: (
            -item["relevance_score"],
            item["file"],
            item["commit_hash"],
        )
    )

    # Stage 4: Build the unified investigation report.
    total_commits = sum(
        len(commits)
        for commits in git_history.values()
    )

    report = {
        "incident": incident,
        "investigation_status": (
            "evidence_found" if source_evidence else "no_source_evidence"
        ),
        "source_evidence": source_evidence,
        "git_history": git_history,
        "potentially_relevant_commits": potentially_relevant_commits,
        "statistics": {
            "source_matches": len(source_evidence),
            "files_investigated": len(source_files),
            "commits_found": total_commits,
            "potentially_relevant_commits": len(
                potentially_relevant_commits
            ),
        },
        "diagnosis": {
            "root_cause_confirmed": False,
            "message": (
                "Evidence collected. Potentially relevant commits identified "
                "through keyword correlation. Further analysis is required "
                "to establish the root cause."
            ),
        },
    }
    return InvestigationReport.model_validate(report).model_dump(
        mode="python",
        exclude_unset=True,
    )


def calculate_recency_score(commit_date: str) -> float:
    """
    Calculate a recency score between 0 and 1.

    Newer commits receive higher scores.
    A commit approximately 30 days old receives
    half the score of a newly created commit.
    """

    try:
        parsed_date = datetime.fromisoformat(commit_date)

        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)

        current_time = datetime.now(timezone.utc)
        age_days = max(
            0,
            (current_time - parsed_date.astimezone(timezone.utc)).total_seconds()
            / 86400,
        )

        return round(0.5 ** (age_days / 30), 4)

    except (TypeError, ValueError):
        return 0.0