
from app.services.incident_analyzer import analyze_incidents


def test_database_failures_are_grouped():

    events = [
        {
            "failure_type": "database",
            "status_code": 503,
            "endpoint": "/simulate-failure",
            "message": "Database connection failed"
        },
        {
            "failure_type": "database",
            "status_code": 503,
            "endpoint": "/simulate-failure",
            "message": "Database connection failed"
        }
    ]

    result = analyze_incidents(events)

    assert len(result) == 1
    assert result[0]["failure_type"] == "database"
    assert result[0]["total_occurrences"] == 2
    assert 503 in result[0]["status_codes"]


def test_payment_failures_are_grouped():

    events = [
        {
            "failure_type": "payment",
            "status_code": 502,
            "endpoint": "/simulate-failure",
            "message": "Payment gateway timeout"
        },
        {
            "failure_type": "payment",
            "status_code": 502,
            "endpoint": "/simulate-failure",
            "message": "Payment gateway timeout"
        }
    ]

    result = analyze_incidents(events)

    assert len(result) == 1
    assert result[0]["failure_type"] == "payment"
    assert result[0]["total_occurrences"] == 2
    assert 502 in result[0]["status_codes"]


def test_empty_events_return_empty_result():

    result = analyze_incidents([])

    assert result == []


def test_unknown_failure_type_is_handled():

    events = [
        {
            "status_code": 500,
            "endpoint": "/unknown",
            "message": "Unexpected error"
        }
    ]

    result = analyze_incidents(events)

    assert len(result) == 1
    assert result[0]["failure_type"] == "unknown"
    assert result[0]["total_occurrences"] == 1
