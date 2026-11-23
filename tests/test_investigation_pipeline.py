from unittest.mock import patch
from datetime import datetime, timezone
from app.services.investigation_pipeline import investigate_incident
from app.services.investigation_pipeline import calculate_recency_score

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
    ):
        report = investigate_incident(incident)

    matches = report["potentially_relevant_commits"]

    assert len(matches) == 1
    assert matches[0]["commit_hash"] == "abc123"
    assert "database" in matches[0]["matching_keywords"]
    assert report["statistics"]["potentially_relevant_commits"] == 1
    assert report["diagnosis"]["root_cause_confirmed"] is False


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