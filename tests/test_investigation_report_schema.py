from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas import (
    ChangeEvidence,
    InvestigationReport,
    InvestigationStatistics,
    LineFunctionMatch,
    SourceEvidence,
)


def _valid_report() -> dict:
    return {
        "incident": {
            "failure_type": "database",
            "message": "Database connection failed",
            "endpoint": "/orders",
        },
        "investigation_status": "evidence_found",
        "source_evidence": [{
            "file": "app/services/database.py",
            "line_number": 10,
            "matching_keywords": ["database", "connection"],
            "relevance_score": 6,
            "code_snippet": "connect_database()",
            "start_line": 8,
            "end_line": 12,
            "context": "context lines",
            "function": None,
        }],
        "git_history": {
            "app/services/database.py": [{
                "commit_hash": "abc123",
                "short_hash": "abc123",
                "author": "Test Author",
                "date": "2026-01-01T00:00:00+00:00",
                "message": "Update database connection",
                "changed_files": ["app/services/database.py"],
            }],
        },
        "potentially_relevant_commits": [{
            "file": "app/services/database.py",
            "commit_hash": "abc123",
            "message": "Update database connection",
            "matching_keywords": ["database"],
            "keyword_score": 0.5,
            "source_relevance_score": 0.6,
            "recency_score": 0.7,
            "relevance_score": 0.6,
            "change_evidence": {
                "file_path": "app/services/database.py",
                "commit_hash": "abc123",
                "added_lines": [{
                    "line_number": 11,
                    "content": "retry_connection()",
                }],
                "deleted_lines": [],
                "overlaps_suspicious_source_evidence": False,
                "source_evidence_overlap_status": "available",
                "added_lines_overlap_historical_function": True,
                "matching_function_names": ["connect_database"],
                "matching_added_function_names": ["connect_database"],
                "matching_deleted_function_names": [],
                "added_line_function_matches": [{
                    "line_number": 11,
                    "function_names": ["connect_database"],
                }],
                "deleted_line_function_matches": [],
                "historical_ast_status": "available",
                "deleted_historical_ast_status": "not_required",
                "status": "available",
                "note": "Line overlap is supporting evidence only.",
            },
        }],
        "statistics": {
            "source_matches": 1,
            "files_investigated": 1,
            "commits_found": 1,
            "potentially_relevant_commits": 1,
        },
        "diagnosis": {
            "root_cause_confirmed": False,
            "message": "Further analysis is required.",
        },
    }


def test_valid_complete_report_validates():
    report = InvestigationReport.model_validate(_valid_report())

    assert report.investigation_status == "evidence_found"
    assert report.source_evidence[0].function is None
    assert report.model_dump()["statistics"]["commits_found"] == 1


def test_empty_evidence_report_validates():
    payload = _valid_report()
    payload.update({
        "investigation_status": "no_source_evidence",
        "source_evidence": [],
        "git_history": {},
        "potentially_relevant_commits": [],
        "statistics": {
            "source_matches": 0,
            "files_investigated": 0,
            "commits_found": 0,
            "potentially_relevant_commits": 0,
        },
    })

    report = InvestigationReport.model_validate(payload)

    assert report.source_evidence == []
    assert report.git_history == {}
    assert report.potentially_relevant_commits == []


def test_raw_source_relevance_score_can_exceed_one():
    evidence = SourceEvidence.model_validate({
        **_valid_report()["source_evidence"][0],
        "relevance_score": 9,
    })

    assert evidence.relevance_score == 9


def test_invalid_source_evidence_overlap_status_is_rejected():
    evidence = _valid_report()["potentially_relevant_commits"][0][
        "change_evidence"
    ]
    evidence["source_evidence_overlap_status"] = "unknown"

    with pytest.raises(ValidationError):
        ChangeEvidence.model_validate(evidence)


def test_invalid_deleted_historical_ast_status_is_rejected():
    evidence = _valid_report()["potentially_relevant_commits"][0][
        "change_evidence"
    ]
    evidence["deleted_historical_ast_status"] = "unknown"

    with pytest.raises(ValidationError):
        ChangeEvidence.model_validate(evidence)


def test_source_evidence_rejects_reversed_line_boundaries():
    evidence = deepcopy(_valid_report()["source_evidence"][0])
    evidence["start_line"] = 13
    evidence["end_line"] = 12

    with pytest.raises(ValidationError, match="start_line"):
        SourceEvidence.model_validate(evidence)


@pytest.mark.parametrize(
    "field",
    [
        "source_matches",
        "files_investigated",
        "commits_found",
        "potentially_relevant_commits",
    ],
)
def test_negative_statistics_counts_are_rejected(field):
    statistics = {
        "source_matches": 0,
        "files_investigated": 0,
        "commits_found": 0,
        "potentially_relevant_commits": 0,
    }
    statistics[field] = -1

    with pytest.raises(ValidationError):
        InvestigationStatistics.model_validate(statistics)


def test_line_function_match_rejects_zero_line_number():
    with pytest.raises(ValidationError):
        LineFunctionMatch.model_validate({
            "line_number": 0,
            "function_names": [],
        })


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("keyword_score", 1.01),
        ("keyword_score", -0.01),
        ("source_relevance_score", 1.01),
        ("recency_score", -0.01),
        ("relevance_score", 1.01),
    ],
)
def test_candidate_scores_must_be_between_zero_and_one(field, value):
    candidate = deepcopy(_valid_report()["potentially_relevant_commits"][0])
    candidate[field] = value

    with pytest.raises(ValidationError):
        from app.schemas import RelevantCommit

        RelevantCommit.model_validate(candidate)


@pytest.mark.parametrize(
    ("model", "payload", "field"),
    [
        (
            "changed_line",
            {"line_number": 0, "content": "bad"},
            "line_number",
        ),
        (
            "function",
            {
                "function_name": "broken",
                "start_line": 4,
                "end_line": 3,
                "is_async": False,
            },
            "start_line",
        ),
    ],
)
def test_invalid_line_numbers_and_function_boundaries_are_rejected(
    model,
    payload,
    field,
):
    from app.schemas import ChangedLine, SourceFunctionEvidence

    model_type = {
        "changed_line": ChangedLine,
        "function": SourceFunctionEvidence,
    }[model]
    with pytest.raises(ValidationError):
        model_type.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("investigation_status", "unknown"),
        ("change_status", "unknown"),
        ("ast_status", "unknown"),
    ],
)
def test_invalid_status_values_are_rejected(field, value):
    payload = _valid_report()
    if field == "investigation_status":
        payload["investigation_status"] = value
    else:
        evidence = payload["potentially_relevant_commits"][0][
            "change_evidence"
        ]
        evidence[
            "status" if field == "change_status" else "historical_ast_status"
        ] = value

    with pytest.raises(ValidationError):
        InvestigationReport.model_validate(payload)


def test_unavailable_source_overlap_cannot_be_true():
    evidence = _valid_report()["potentially_relevant_commits"][0][
        "change_evidence"
    ]
    evidence["source_evidence_overlap_status"] = "unavailable"
    evidence["overlaps_suspicious_source_evidence"] = True

    with pytest.raises(ValidationError, match="source evidence overlap"):
        ChangeEvidence.model_validate(evidence)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("investigation_status",), "no_source_evidence"),
        (("statistics", "source_matches"), 2),
        (("statistics", "files_investigated"), 2),
        (("statistics", "commits_found"), 2),
        (("statistics", "potentially_relevant_commits"), 2),
    ],
)
def test_report_inconsistencies_are_rejected(path, value):
    payload = _valid_report()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        InvestigationReport.model_validate(payload)


def test_extra_fields_are_preserved():
    payload = _valid_report()
    payload["future_report_field"] = {"enabled": True}
    payload["source_evidence"][0]["future_source_field"] = "preserved"
    payload["potentially_relevant_commits"][0]["change_evidence"][
        "future_change_field"
    ] = 42

    dumped = InvestigationReport.model_validate(payload).model_dump()

    assert dumped["future_report_field"] == {"enabled": True}
    assert dumped["source_evidence"][0]["future_source_field"] == "preserved"
    assert dumped["potentially_relevant_commits"][0]["change_evidence"][
        "future_change_field"
    ] == 42


def test_optional_error_fields_and_explicit_none_function_are_preserved():
    payload = _valid_report()
    change_evidence = payload["potentially_relevant_commits"][0][
        "change_evidence"
    ]
    change_evidence["error_reason"] = "Diff unavailable."

    dumped = InvestigationReport.model_validate(payload).model_dump(
        exclude_unset=True,
    )

    assert dumped["source_evidence"][0]["function"] is None
    assert (
        dumped["potentially_relevant_commits"][0]["change_evidence"][
            "error_reason"
        ]
        == "Diff unavailable."
    )
    assert (
        "historical_ast_error_reason"
        not in dumped["potentially_relevant_commits"][0]["change_evidence"]
    )
