
from pathlib import Path

import pytest

from app.services import source_code_analyzer
from app.services.source_code_analyzer import search_source_code

def test_database_incident_finds_relevant_source():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    }

    results = search_source_code(incident)

    assert isinstance(results, list)
    assert len(results) > 0

    assert any(
        "database" in keyword
        for result in results
        for keyword in result["matching_keywords"]
    )


def test_empty_incident_returns_no_results():
    incident = {
        "failure_type": "",
        "message": "",
        "endpoint": "",
    }

    results = search_source_code(incident)

    assert results == []


def test_result_limit_is_respected():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    }

    results = search_source_code(incident, max_results=2)

    assert len(results) <= 2


def test_invalid_incident_type_raises_error():
    try:
        search_source_code("database")

    except TypeError:
        assert True

    else:
        assert False, "Expected TypeError"


def test_invalid_result_limit_raises_error():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }

    try:
        search_source_code(incident, max_results=0)

    except ValueError:
        assert True

    else:
        assert False, "Expected ValueError"



def test_database_evidence_is_ranked_above_payment_evidence():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    }

    results = search_source_code(incident)

    assert results

    scores = [
        result["relevance_score"]
        for result in results
    ]

    assert scores == sorted(scores, reverse=True)

    # Payment-specific evidence must not appear in database results.
    payment_only_matches = [
        result
        for result in results
        if "payment" in result["matching_keywords"]
        and "database" not in result["matching_keywords"]
    ]

    assert payment_only_matches == []

def test_missing_source_directory_returns_empty_list(monkeypatch, tmp_path):
    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        tmp_path / "missing",
    )

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "/simulate-failure",
    }

    assert search_source_code(incident) == []


def test_unreadable_source_file_is_skipped(monkeypatch, tmp_path):
    source_file = tmp_path / "example.py"
    source_file.write_text("database connection failed", encoding="utf-8")

    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        tmp_path,
    )
    monkeypatch.setattr(
        source_code_analyzer.Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Read failed")),
    )

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    assert search_source_code(incident) == []


def test_unicode_decode_error_is_skipped(monkeypatch, tmp_path):
    source_file = tmp_path / "example.py"
    source_file.write_text("database connection failed", encoding="utf-8")

    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        tmp_path,
    )
    monkeypatch.setattr(
        source_code_analyzer.Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(UnicodeDecodeError(
            "utf-8", b"\xff", 0, 1, "invalid start byte"
        )),
    )

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    assert search_source_code(incident) == []


def test_endpoint_only_low_relevance_match_is_excluded(monkeypatch, tmp_path):
    source_file = tmp_path / "example.py"
    source_file.write_text(
        'endpoint = "/orders"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        tmp_path,
    )

    incident = {
        "failure_type": "",
        "message": "",
        "endpoint": "/orders",
    }

    assert search_source_code(incident) == []

def test_non_integer_result_limit_raises_type_error():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    with pytest.raises(TypeError, match="max_results must be an integer"):
        search_source_code(incident, max_results="5")



def test_source_evidence_includes_function_metadata():
    incident = {
        "failure_type": "database",
        "message": "Unable to establish database connection",
        "endpoint": "/simulate-failure",
    }

    results = search_source_code(incident)

    assert results

    matching_result = next(
        result
        for result in results
        if result["file"].replace("\\", "/") == "app/api/routes.py"
        and result["function"] is not None
        and result["function"]["function_name"] == "simulate_failure"
    )

    function_info = matching_result["function"]

    assert function_info["start_line"] <= matching_result["line_number"]
    assert matching_result["line_number"] <= function_info["end_line"]
    assert function_info["is_async"] is False
