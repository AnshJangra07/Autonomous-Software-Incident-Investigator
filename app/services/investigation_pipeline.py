from datetime import datetime, timezone
from app.services.source_code_analyzer import (
    search_source_code,
    extract_keywords,
)
from app.services.git_history_analyzer import get_file_commit_history


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