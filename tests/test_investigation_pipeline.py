
from app.services.investigation_pipeline import investigate_incident


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
