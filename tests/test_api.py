import pytest

from fastapi.testclient import TestClient

from app.main import app


def _investigation_report(incident, include_source_evidence=True):
    source_evidence = []
    git_history = {}
    if include_source_evidence:
        source_evidence = [{
            "file": "app/services/database.py",
            "line_number": 10,
            "matching_keywords": ["database"],
            "relevance_score": 3,
            "code_snippet": "connect_database()",
            "start_line": 8,
            "end_line": 12,
            "context": "context lines",
            "function": None,
        }]
        git_history = {
            "app/services/database.py": [{
                "commit_hash": "abc123",
                "short_hash": "abc123",
                "author": "Test Author",
                "date": "2026-01-01T00:00:00+00:00",
                "message": "Update database connection",
                "changed_files": ["app/services/database.py"],
            }],
        }

    return {
        "incident": incident,
        "investigation_status": (
            "evidence_found" if source_evidence else "no_source_evidence"
        ),
        "source_evidence": source_evidence,
        "git_history": git_history,
        "potentially_relevant_commits": [],
        "statistics": {
            "source_matches": len(source_evidence),
            "files_investigated": len(git_history),
            "commits_found": sum(
                len(commits) for commits in git_history.values()
            ),
            "potentially_relevant_commits": 0,
        },
        "diagnosis": {
            "root_cause_confirmed": False,
            "message": "Further analysis is required.",
        },
    }


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_investigation_endpoint_returns_report(client, monkeypatch):
    def mock_investigation(incident):
        assert incident["failure_type"] == "database"
        assert incident["message"] == "Database connection failed"
        return _investigation_report(incident)

    monkeypatch.setattr(
        "app.api.routes.investigate_incident",
        mock_investigation,
    )

    response = client.post(
        "/investigations/run",
        json={
            "failure_type": "database",
            "message": "Database connection failed",
            "endpoint": "/simulate-failure",
        },
    )

    assert response.status_code == 200
    response_report = response.json()
    assert response_report == _investigation_report({
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    })
    assert {
        "incident",
        "investigation_status",
        "source_evidence",
        "git_history",
        "potentially_relevant_commits",
        "statistics",
        "diagnosis",
    }.issubset(response_report)


def test_investigation_endpoint_handles_empty_source_evidence(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.routes.investigate_incident",
        lambda incident: _investigation_report(
            incident,
            include_source_evidence=False,
        ),
    )

    response = client.post(
        "/investigations/run",
        json={
            "failure_type": "database",
            "message": "No matching source",
            "endpoint": "/simulate-failure",
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["investigation_status"] == "no_source_evidence"
    assert report["source_evidence"] == []
    assert report["git_history"] == {}
    assert report["statistics"] == {
        "source_matches": 0,
        "files_investigated": 0,
        "commits_found": 0,
        "potentially_relevant_commits": 0,
    }


def test_investigation_endpoint_rejects_missing_fields(client):

    response = client.post(
        "/investigations/run",
        json={
            "failure_type": "database",
        },
    )

    assert response.status_code == 422



def test_home_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "E-commerce application is running",
        "application": "ASII Demo Store",
    }


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "ecommerce-api",
    }


def test_database_failure_simulation(client):
    response = client.get(
        "/simulate-failure",
        params={"failure_type": "database"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Simulated database connection failure"
    )


def test_payment_failure_simulation(client):
    response = client.get(
        "/simulate-failure",
        params={"failure_type": "payment"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Simulated payment gateway timeout"
    )


def test_invalid_failure_type_is_rejected(client):
    response = client.get(
        "/simulate-failure",
        params={"failure_type": "network"},
    )

    assert response.status_code == 422


def test_recent_incidents_endpoint(client, monkeypatch):
    from app.api import routes

    sample_incidents = [
        {"level": "ERROR", "failure_type": "database"},
        {"level": "ERROR", "failure_type": "payment"},
    ]

    monkeypatch.setattr(
        routes,
        "read_error_events",
        lambda limit: sample_incidents,
    )

    response = client.get("/incidents/recent")

    assert response.status_code == 200
    assert response.json()["total_incidents"] == 2
    assert response.json()["incidents"] == sample_incidents


def test_recent_incidents_limit_validation(client):
    response = client.get(
        "/incidents/recent",
        params={"limit": 0},
    )

    assert response.status_code == 422


def test_incident_summary_endpoint(client, monkeypatch):
    from app.api import routes

    sample_incidents = [
        {"level": "ERROR", "failure_type": "database"},
    ]

    sample_summaries = [
        {"failure_type": "database", "total_occurrences": 1},
    ]

    monkeypatch.setattr(
        routes,
        "read_error_events",
        lambda limit: sample_incidents,
    )

    monkeypatch.setattr(
        routes,
        "analyze_incidents",
        lambda incidents: sample_summaries,
    )

    response = client.get("/incidents/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_error_events": 1,
        "total_incident_types": 1,
        "incident_summaries": sample_summaries,
    }
