import pytest

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_investigation_endpoint_returns_report(client, monkeypatch):

    expected_report = {
        "investigation_status": "evidence_found",
        "source_evidence": [],
        "git_history": {},
        "statistics": {
            "source_matches": 0,
            "files_investigated": 0,
            "commits_found": 0,
        },
        "diagnosis": {
            "root_cause_confirmed": False,
        },
    }

    def mock_investigation(incident):
        assert incident["failure_type"] == "database"
        assert incident["message"] == "Database connection failed"

        return expected_report

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
    assert response.json() == expected_report


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
