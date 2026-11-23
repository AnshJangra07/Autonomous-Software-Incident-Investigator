
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
