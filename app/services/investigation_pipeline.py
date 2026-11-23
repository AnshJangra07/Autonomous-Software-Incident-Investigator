from datetime import datetime, timezone
from typing import Literal

from git.exc import BadObject, GitError, InvalidGitRepositoryError, NoSuchPathError

from app.services.source_code_analyzer import (
    search_source_code,
    extract_keywords,
)
from app.services.git_diff_analyzer import get_commit_diff
from app.services.diff_change_analyzer import extract_changed_lines
from app.services.git_history_analyzer import get_file_commit_history


def _empty_change_evidence(
    file_path: str,
    commit_hash: str,
    status: Literal["no_diff", "unavailable", "invalid_diff"],
    error_reason: str | None = None,
) -> dict:
    """Build change evidence when no usable changed lines are available."""
    evidence = {
        "file_path": file_path,
        "commit_hash": commit_hash,
        "added_lines": [],
        "deleted_lines": [],
        "overlaps_suspicious_source_evidence": False,
        "overlaps_suspicious_function": False,
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
    """Correlate a commit's changed lines with suspicious source locations."""
    try:
        diff_result = get_commit_diff(commit_hash, file_path)
    except (
        BadObject,
        GitError,
        InvalidGitRepositoryError,
        NoSuchPathError,
    ):
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "unavailable",
            "Git diff could not be retrieved.",
        )

    if not isinstance(diff_result, dict):
        return _empty_change_evidence(
            file_path,
            commit_hash,
            "unavailable",
            "Git diff result was missing or unusable.",
        )

    if diff_result.get("diff_found") is False:
        return _empty_change_evidence(file_path, commit_hash, "no_diff")

    if (
        "diff_found" in diff_result
        and not isinstance(diff_result["diff_found"], bool)
    ):
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

    added_line_numbers = {
        line["line_number"]
        for line in changes["added_lines"]
    }

    file_evidence = [
        evidence
        for evidence in source_evidence
        if evidence.get("file") == file_path
    ]

    suspicious_line_numbers = {
        evidence.get("line_number")
        for evidence in file_evidence
    }
    overlaps_suspicious_source = bool(
        added_line_numbers.intersection(suspicious_line_numbers)
    )

    matching_function_names = set()
    overlaps_suspicious_function = False

    for evidence in file_evidence:
        function = evidence.get("function")
        if not isinstance(function, dict):
            continue

        start_line = function.get("start_line")
        end_line = function.get("end_line")
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            continue

        overlapping_lines = {
            line_number
            for line_number in added_line_numbers
            if start_line <= line_number <= end_line
        }
        if not overlapping_lines:
            continue

        overlaps_suspicious_function = True
        function_name = function.get("function_name")
        if isinstance(function_name, str) and function_name:
            matching_function_names.add(function_name)

    return {
        "file_path": file_path,
        "commit_hash": commit_hash,
        "added_lines": changes["added_lines"],
        "deleted_lines": changes["deleted_lines"],
        "overlaps_suspicious_source_evidence": overlaps_suspicious_source,
        "overlaps_suspicious_function": overlaps_suspicious_function,
        "matching_function_names": sorted(matching_function_names),
        "status": (
            "available"
            if changes["added_lines"] or changes["deleted_lines"]
            else "no_diff"
        ),
        "note": (
            "Line overlap is supporting evidence only and does not prove "
            "causality."
        ),
    }


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
        isinstance(max_commits_per_file, bool)
        or not isinstance(max_commits_per_file, int)
    ):
        raise TypeError("max_commits_per_file must be an integer")

    if max_commits_per_file < 1:
        raise ValueError("max_commits_per_file must be greater than zero")

    # Stage 1: Find relevant source-code locations.
    source_evidence = search_source_code(
        incident,
        max_results=max_source_results,
    )

    # Stage 2: Retrieve Git history for each unique source file.
    git_history = {}

    source_files = sorted({
        result["file"]
        for result in source_evidence
    })

    for file_path in source_files:
        git_history[file_path] = get_file_commit_history(
            file_path,
            max_commits=max_commits_per_file,
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

    return {
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