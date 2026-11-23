
import json
import pytest
from app.services import log_collector


def test_reads_valid_error_events(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"

    events = [
        {"level": "ERROR", "message": "Database connection failed"},
        {"level": "INFO", "message": "Health check successful"},
        {"level": "ERROR", "message": "Payment gateway timeout"},
    ]

    log_file.write_text(
        "\n".join(json.dumps(event) for event in events),
        encoding="utf-8",
    )

    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    results = log_collector.read_error_events()

    assert len(results) == 2
    assert all(event["level"] == "ERROR" for event in results)


def test_missing_log_file_returns_empty_list(tmp_path, monkeypatch):
    log_file = tmp_path / "missing.log"

    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    assert log_collector.read_error_events() == []


def test_malformed_json_lines_are_skipped(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"

    log_file.write_text(
        '{"level": "ERROR", "message": "Database failed"}\n'
        'this is not valid JSON\n'
        '{"level": "ERROR", "message": "Payment failed"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    results = log_collector.read_error_events()

    assert len(results) == 2


def test_limit_returns_only_latest_error_events(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"

    events = [
        {"level": "ERROR", "message": f"Error {number}"}
        for number in range(5)
    ]

    log_file.write_text(
        "\n".join(json.dumps(event) for event in events),
        encoding="utf-8",
    )

    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    results = log_collector.read_error_events(limit=2)

    assert len(results) == 2
    assert results[0]["message"] == "Error 3"
    assert results[1]["message"] == "Error 4"


def test_maximum_limit_returns_latest_error_events(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"
    events = [
        {"level": "ERROR", "message": f"Error {number}"}
        for number in range(105)
    ]
    log_file.write_text(
        "\n".join(json.dumps(event) for event in events),
        encoding="utf-8",
    )
    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    results = log_collector.read_error_events(limit=100)

    assert len(results) == 100
    assert results[0]["message"] == "Error 5"
    assert results[-1]["message"] == "Error 104"


def test_default_limit_is_preserved(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"
    events = [
        {"level": "ERROR", "message": f"Error {number}"}
        for number in range(25)
    ]
    log_file.write_text(
        "\n".join(json.dumps(event) for event in events),
        encoding="utf-8",
    )
    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    results = log_collector.read_error_events()

    assert len(results) == 20
    assert results[0]["message"] == "Error 5"
    assert results[-1]["message"] == "Error 24"


def test_limit_above_maximum_is_rejected():
    with pytest.raises(ValueError, match="limit must not exceed 100"):
        log_collector.read_error_events(limit=101)


def test_zero_limit_returns_empty_list(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"

    log_file.write_text(
        '{"level": "ERROR", "message": "Database failed"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(log_collector, "LOG_FILE", log_file)

    assert log_collector.read_error_events(limit=0) == []


def test_non_integer_limit_is_rejected():
    with pytest.raises(TypeError):
        log_collector.read_error_events(limit="5")


def test_negative_limit_is_rejected():
    with pytest.raises(ValueError):
        log_collector.read_error_events(limit=-1)


def test_boolean_limit_is_rejected():
    with pytest.raises(TypeError):
        log_collector.read_error_events(limit=True)
