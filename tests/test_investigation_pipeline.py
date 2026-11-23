import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from git.exc import BadObject, GitCommandError, InvalidGitRepositoryError

from app.services.investigation_pipeline import (
    _analyze_commit_changes,
    calculate_recency_score,
    investigate_incident,
)

def test_database_investigation_returns_structured_report():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    }

    report = investigate_incident(incident)

    assert report["investigation_status"] == "evidence_found"
    assert len(report["source_evidence"]) > 0
    assert "git_history" in report
    assert "statistics" in report
    assert report["diagnosis"]["root_cause_confirmed"] is False


def test_investigation_statistics_are_consistent():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    }

    report = investigate_incident(incident)

    assert (
        report["statistics"]["source_matches"]
        == len(report["source_evidence"])
    )

    assert (
        report["statistics"]["files_investigated"]
        == len(report["git_history"])
    )


def test_invalid_incident_type_is_rejected():
    try:
        investigate_incident("database")

    except TypeError:
        assert True

    else:
        assert False, "Expected TypeError"


def test_invalid_commit_limit_is_rejected():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }

    try:
        investigate_incident(
            incident,
            max_commits_per_file=0,
        )

    except ValueError:
        assert True

    else:
        assert False, "Expected ValueError"



def test_incident_keywords_match_relevant_git_commits():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    }

    source_evidence = [
        {"file": "app/services/database.py"}
    ]

    git_history = [
        {
            "commit_hash": "abc123",
            "message": "Update database connection pooling",
        },
        {
            "commit_hash": "def456",
            "message": "Improve frontend styling",
        },
    ]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_evidence,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=git_history,
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ):
        report = investigate_incident(incident)

    matches = report["potentially_relevant_commits"]

    assert len(matches) == 1
    assert matches[0]["commit_hash"] == "abc123"
    assert "database" in matches[0]["matching_keywords"]
    assert report["statistics"]["potentially_relevant_commits"] == 1
    assert report["diagnosis"]["root_cause_confirmed"] is False
    assert matches[0]["relevance_score"] > 0
    assert matches[0]["change_evidence"]["added_lines"] == []


def _investigate_with_changes(source_evidence, diff_result):
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }
    git_history = [{
        "commit_hash": "abc123",
        "message": "Database connection failed",
    }]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_evidence,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=git_history,
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value=diff_result,
    ):
        return investigate_incident(incident)


def _change_evidence(report):
    return report["potentially_relevant_commits"][0]["change_evidence"]


def _analyze_diff_result(diff_result):
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value=diff_result,
    ):
        return _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )


@pytest.mark.parametrize(
    ("diff_result", "expected_status", "has_error_reason"),
    [
        (None, "unavailable", True),
        ({}, "unavailable", True),
        ({"diff_found": False}, "no_diff", False),
        ({"diff_found": True}, "unavailable", True),
        ({"diff_found": True, "patch": None}, "invalid_diff", True),
        ({"diff_found": True, "patch": 123}, "invalid_diff", True),
        ({"diff_found": "yes", "patch": ""}, "unavailable", True),
        ({"diff_found": True, "patch": ""}, "no_diff", False),
    ],
)
def test_classifies_missing_unexpected_and_empty_diff_results(
    diff_result,
    expected_status,
    has_error_reason,
):
    evidence = _analyze_diff_result(diff_result)

    assert evidence["status"] == expected_status
    assert ("error_reason" in evidence) is has_error_reason
    if has_error_reason:
        assert evidence["error_reason"]


@pytest.mark.parametrize(
    "parse_error",
    [
        ValueError("private parser detail"),
        TypeError("private parser detail"),
    ],
)
def test_parser_errors_return_invalid_diff_without_internal_details(parse_error):
    diff_result = {"diff_found": True, "patch": "@@ -1 +1 @@\n+new\n"}
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value=diff_result,
    ), patch(
        "app.services.investigation_pipeline.extract_changed_lines",
        side_effect=parse_error,
    ):
        evidence = _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )

    assert evidence["status"] == "invalid_diff"
    assert evidence["error_reason"] == "Git patch could not be parsed."
    assert "private parser detail" not in evidence["error_reason"]


def test_malformed_patch_returns_invalid_diff():
    evidence = _analyze_diff_result({
        "diff_found": True,
        "patch": "@@ malformed @@\n+new\n",
    })

    assert evidence["status"] == "invalid_diff"
    assert evidence["error_reason"] == "Git patch could not be parsed."


@pytest.mark.parametrize(
    "git_error",
    [
        GitCommandError("git diff", 1),
        InvalidGitRepositoryError("private repository path"),
        BadObject("private object id"),
    ],
)
def test_expected_git_retrieval_errors_return_unavailable(git_error):
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        side_effect=git_error,
    ):
        evidence = _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )

    assert evidence["status"] == "unavailable"
    assert evidence["error_reason"] == "Git diff could not be retrieved."
    assert "private" not in evidence["error_reason"]


def test_unexpected_programming_error_from_diff_retrieval_is_not_hidden():
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        side_effect=RuntimeError("unexpected programming error"),
    ):
        with pytest.raises(RuntimeError, match="unexpected programming error"):
            _analyze_commit_changes(
                "app/services/database.py",
                "abc123",
                [],
            )


def test_added_line_overlapping_suspicious_source_evidence():
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 10,
            "function": None,
        }],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+changed line\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "available"
    assert evidence["overlaps_suspicious_source_evidence"] is True
    assert evidence["overlaps_suspicious_function"] is False
    assert evidence["added_lines"] == [
        {"line_number": 10, "content": "changed line"},
    ]


def test_added_line_overlapping_suspicious_function():
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 5,
            "function": {
                "function_name": "connect_database",
                "start_line": 8,
                "end_line": 12,
            },
        }],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+changed line\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["overlaps_suspicious_source_evidence"] is False
    assert evidence["overlaps_suspicious_function"] is True
    assert evidence["matching_function_names"] == ["connect_database"]


def test_added_line_outside_suspicious_functions():
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 5,
            "function": {
                "function_name": "connect_database",
                "start_line": 4,
                "end_line": 6,
            },
        }],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+changed line\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["overlaps_suspicious_source_evidence"] is False
    assert evidence["overlaps_suspicious_function"] is False
    assert evidence["matching_function_names"] == []


def test_commit_with_no_diff_has_empty_change_evidence():
    report = _investigate_with_changes(
        [{"file": "app/services/database.py", "line_number": 10}],
        {"diff_found": False, "patch": ""},
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "no_diff"
    assert evidence["added_lines"] == []
    assert evidence["deleted_lines"] == []
    assert evidence["overlaps_suspicious_source_evidence"] is False
    assert evidence["overlaps_suspicious_function"] is False


def test_commit_with_no_added_lines_only_reports_deletions():
    report = _investigate_with_changes(
        [{"file": "app/services/database.py", "line_number": 10}],
        {
            "diff_found": True,
            "patch": "@@ -10 +9,0 @@\n-deleted line\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "available"
    assert evidence["added_lines"] == []
    assert evidence["deleted_lines"] == [
        {"line_number": 10, "content": "deleted line"},
    ]
    assert evidence["overlaps_suspicious_source_evidence"] is False
    assert evidence["overlaps_suspicious_function"] is False


def test_missing_diff_result_is_handled_as_empty_evidence():
    report = _investigate_with_changes(
        [{"file": "app/services/database.py", "line_number": 10}],
        None,
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "unavailable"
    assert evidence["error_reason"] == (
        "Git diff result was missing or unusable."
    )
    assert evidence["added_lines"] == []
    assert evidence["deleted_lines"] == []


def test_multiple_added_lines_are_correlated_with_evidence_and_functions():
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 11,
            "function": {
                "function_name": "connect_database",
                "start_line": 10,
                "end_line": 11,
            },
        }],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,3 @@\n context\n+first\n+second\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["added_lines"] == [
        {"line_number": 10, "content": "first"},
        {"line_number": 11, "content": "second"},
    ]
    assert evidence["overlaps_suspicious_source_evidence"] is True
    assert evidence["overlaps_suspicious_function"] is True
    assert evidence["matching_function_names"] == ["connect_database"]
    assert "does not prove causality" in evidence["note"]


def test_change_evidence_preserves_existing_candidate_scoring_and_fields():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }
    source_evidence = [{
        "file": "app/services/database.py",
        "line_number": 10,
        "relevance_score": 8,
        "function": None,
    }]
    git_history = [{
        "commit_hash": "abc123",
        "message": "Database connection failed",
    }]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_evidence,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=git_history,
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ) as get_commit_diff, patch(
        "app.services.investigation_pipeline.calculate_recency_score",
        return_value=0.5,
    ):
        report = investigate_incident(incident)

    candidate = report["potentially_relevant_commits"][0]

    get_commit_diff.assert_called_once_with(
        "abc123",
        "app/services/database.py",
    )
    assert candidate["relevance_score"] == 0.84
    assert candidate["file"] == "app/services/database.py"
    assert candidate["commit_hash"] == "abc123"
    assert candidate["message"] == "Database connection failed"
    assert candidate["matching_keywords"] == [
        "connection",
        "database",
        "failed",
    ]
    assert candidate["change_evidence"]["file_path"] == candidate["file"]


def test_no_commit_matches_returns_empty_list():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=[{"file": "app/services/database.py"}],
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=[
            {
                "commit_hash": "xyz123",
                "message": "Update frontend styling",
            }
        ],
    ):
        report = investigate_incident(incident)

    assert report["potentially_relevant_commits"] == []
    assert report["statistics"]["potentially_relevant_commits"] == 0


def test_non_integer_commit_limit_is_rejected():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }

    try:
        investigate_incident(
            incident,
            max_commits_per_file="five",
        )

    except TypeError as error:
        assert str(error) == (
            "max_commits_per_file must be an integer"
        )

    else:
        assert False, "Expected TypeError"


def test_recency_score_is_high_for_recent_commit():
    score = calculate_recency_score(
        datetime.now(timezone.utc).isoformat()
    )

    assert 0.99 <= score <= 1.0


def test_recency_score_is_zero_for_invalid_date():
    assert calculate_recency_score("invalid-date") == 0.0


def test_recency_score_is_zero_for_missing_date():
    assert calculate_recency_score("") == 0.0

def test_recency_score_handles_non_string_date():
    assert calculate_recency_score(None) == 0.0

def test_recency_score_handles_naive_datetime():
    naive_date = datetime.now().isoformat()

    score = calculate_recency_score(naive_date)

    assert 0.99 <= score <= 1.0