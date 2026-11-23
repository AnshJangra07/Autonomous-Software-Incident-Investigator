import logging
import secrets
import string

import pytest
from fastapi.testclient import TestClient

from app.schemas import InvestigationReport
from app.services import log_collector


@pytest.fixture
def isolated_client(tmp_path, monkeypatch):
    from app.core import logging_config

    monkeypatch.setattr(logging_config, "setup_logging", lambda: None)

    from app.main import app
    from app.core.logging_config import JSONFormatter

    log_file = tmp_path / "app.jsonl"
    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    api_logger = logging.getLogger("app.api.routes")
    original_handlers = api_logger.handlers[:]
    original_level = api_logger.level
    original_propagate = api_logger.propagate
    test_handler = logging.FileHandler(log_file, encoding="utf-8")
    test_handler.setFormatter(JSONFormatter())

    for handler in original_handlers:
        api_logger.removeHandler(handler)
    api_logger.addHandler(test_handler)
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False

    try:
        with TestClient(app) as client:
            yield client
    finally:
        api_logger.removeHandler(test_handler)
        test_handler.flush()
        test_handler.close()
        for handler in original_handlers:
            api_logger.addHandler(handler)
        api_logger.setLevel(original_level)
        api_logger.propagate = original_propagate


def _random_word() -> str:
    return "".join(
        secrets.choice(string.ascii_lowercase)
        for _ in range(40)
    )


def test_database_failure_log_to_investigation_report(isolated_client):
    failure_response = isolated_client.get(
        "/simulate-failure",
        params={"failure_type": "database"},
        headers={"X-Request-ID": "e2e-database-failure"},
    )

    assert failure_response.status_code == 503
    assert failure_response.json()["detail"] == (
        "Simulated database connection failure"
    )

    incidents = log_collector.read_error_events()
    incident_event = next(
        event
        for event in incidents
        if event.get("request_id") == "e2e-database-failure"
    )
    assert incident_event["level"] == "ERROR"
    assert incident_event["service"] == "ecommerce-api"
    assert incident_event["endpoint"] == "/simulate-failure"
    assert incident_event["failure_type"] == "database"
    assert incident_event["status_code"] == 503
    assert incident_event["message"] == (
        "Unable to establish database connection"
    )

    incident = {
        "failure_type": incident_event["failure_type"],
        "message": incident_event["message"],
        "endpoint": incident_event["endpoint"],
    }
    investigation_response = isolated_client.post(
        "/investigations/run",
        json=incident,
    )

    assert investigation_response.status_code == 200
    response_data = investigation_response.json()
    assert {
        "incident",
        "investigation_status",
        "source_evidence",
        "git_history",
        "potentially_relevant_commits",
        "statistics",
        "diagnosis",
    }.issubset(response_data)

    report = InvestigationReport.model_validate(response_data)
    assert report.incident == incident
    assert isinstance(report.source_evidence, list)
    assert isinstance(report.git_history, dict)
    assert isinstance(report.potentially_relevant_commits, list)
    assert report.statistics.source_matches == len(report.source_evidence)
    assert report.statistics.files_investigated == len(report.git_history)
    assert report.statistics.commits_found == sum(
        len(commits) for commits in report.git_history.values()
    )
    assert (
        report.statistics.potentially_relevant_commits
        == len(report.potentially_relevant_commits)
    )
    assert report.diagnosis.root_cause_confirmed is False
    assert isinstance(report.diagnosis.message, str)


def test_incident_without_matching_source_returns_empty_evidence(
    isolated_client,
):
    incident = {
        "failure_type": _random_word(),
        "message": _random_word(),
        "endpoint": f"/{_random_word()}",
    }

    response = isolated_client.post(
        "/investigations/run",
        json=incident,
    )

    assert response.status_code == 200
    report = InvestigationReport.model_validate(response.json())
    assert report.investigation_status == "no_source_evidence"
    assert report.source_evidence == []
    assert report.git_history == {}
    assert report.potentially_relevant_commits == []
    assert report.statistics.source_matches == 0
    assert report.statistics.files_investigated == 0
    assert report.statistics.commits_found == 0
    assert report.statistics.potentially_relevant_commits == 0
