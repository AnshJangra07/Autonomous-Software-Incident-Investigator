
from app.services.source_code_analyzer import search_source_code
from app.services.git_history_analyzer import get_file_commit_history


def investigate_incident(
    incident: dict,
    max_source_results: int = 10,
    max_commits_per_file: int = 5,
) -> dict:
    """
    Coordinate source-code and Git-history investigation
    for a single incident event.

    Returns evidence, not a confirmed root-cause diagnosis.
    """

    if not isinstance(incident, dict):
        raise TypeError("incident must be a dictionary")

    if max_commits_per_file < 1:
        raise ValueError("max_commits_per_file must be greater than zero")

    # Stage 1: Find relevant source-code locations.
    source_evidence = search_source_code(
        incident,
        max_results=max_source_results,
    )

    # Stage 2: Investigate Git history for each unique source file.
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

    # Stage 3: Build a unified investigation report.
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
        "statistics": {
            "source_matches": len(source_evidence),
            "files_investigated": len(source_files),
            "commits_found": total_commits,
        },
        "diagnosis": {
            "root_cause_confirmed": False,
            "message": (
                "Evidence collected. Further analysis is required "
                "to establish the root cause."
            ),
        },
    }
