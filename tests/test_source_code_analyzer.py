
import errno
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


def test_maximum_result_limit_is_accepted(monkeypatch, tmp_path):
    source_file = tmp_path / "example.py"
    source_file.write_text(
        'message = "database connection failed"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(source_code_analyzer, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(source_code_analyzer, "SOURCE_DIRECTORY", tmp_path)

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    assert search_source_code(incident, max_results=50)


def test_result_limit_above_maximum_is_rejected():
    with pytest.raises(ValueError, match="max_results must not exceed 50"):
        search_source_code({"failure_type": "database"}, max_results=51)


def test_default_result_limit_is_preserved(monkeypatch, tmp_path):
    source_file = tmp_path / "example.py"
    source_file.write_text(
        "\n".join(
            'message = "database connection failed"'
            for _ in range(12)
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(source_code_analyzer, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(source_code_analyzer, "SOURCE_DIRECTORY", tmp_path)

    results = search_source_code({"failure_type": "database"})

    assert len(results) == 10


def test_boolean_result_limit_is_rejected():
    with pytest.raises(TypeError, match="max_results must be an integer"):
        search_source_code({"failure_type": "database"}, max_results=True)



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


def _skip_if_symlink_unavailable(error):
    unavailable_errnos = {
        errno.EACCES,
        errno.EPERM,
        getattr(errno, "ENOSYS", -1),
        getattr(errno, "ENOTSUP", -1),
        getattr(errno, "EOPNOTSUPP", -1),
    }

    if (
        isinstance(error, NotImplementedError)
        or getattr(error, "errno", None) in unavailable_errnos
        or getattr(error, "winerror", None) == 1314
    ):
        pytest.skip(f"Symlink creation is unavailable: {error}")

    raise error


def test_symlink_to_python_file_outside_source_directory_is_skipped(
    monkeypatch,
    tmp_path,
):
    project_root = tmp_path / "project"
    source_directory = project_root / "app"
    source_directory.mkdir(parents=True)

    outside_file = tmp_path / "outside.py"
    outside_file.write_text(
        'message = "database connection failed"\n',
        encoding="utf-8",
    )

    symlink_file = source_directory / "external.py"
    try:
        symlink_file.symlink_to(outside_file)
    except (NotImplementedError, OSError) as error:
        _skip_if_symlink_unavailable(error)

    monkeypatch.setattr(source_code_analyzer, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        source_directory,
    )

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    assert search_source_code(incident) == []


def test_symlinked_directory_is_not_traversed(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    source_directory = project_root / "app"
    source_directory.mkdir(parents=True)

    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    outside_file = outside_directory / "matching.py"
    outside_file.write_text(
        'message = "database connection failed"\n',
        encoding="utf-8",
    )

    symlink_directory = source_directory / "external"
    try:
        symlink_directory.symlink_to(
            outside_directory,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError) as error:
        _skip_if_symlink_unavailable(error)

    monkeypatch.setattr(source_code_analyzer, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        source_directory,
    )

    resolved_candidates = []
    original_resolve_source_file = source_code_analyzer._resolve_source_file

    def track_candidate(source_file, resolved_source_directory):
        resolved_candidates.append(source_file)
        return original_resolve_source_file(
            source_file,
            resolved_source_directory,
        )

    monkeypatch.setattr(
        source_code_analyzer,
        "_resolve_source_file",
        track_candidate,
    )

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    assert search_source_code(incident) == []
    assert symlink_directory / outside_file.name not in resolved_candidates


def test_normal_python_file_is_still_analyzed(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    source_directory = project_root / "app"
    source_directory.mkdir(parents=True)

    source_file = source_directory / "example.py"
    source_file.write_text(
        'def connect_database():\n'
        '    return "database connection failed"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(source_code_analyzer, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        source_directory,
    )

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    results = search_source_code(incident)

    matching_result = next(
        result
        for result in results
        if result["line_number"] == 2
    )

    assert matching_result["file"] == "app\\example.py"
    assert matching_result["function"]["function_name"] == "connect_database"


def test_unresolvable_candidate_is_skipped(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    source_directory = project_root / "app"
    source_directory.mkdir(parents=True)

    unresolvable_file = source_directory / "unresolvable.py"
    unresolvable_file.write_text(
        'message = "database connection failed"\n',
        encoding="utf-8",
    )

    valid_file = source_directory / "valid.py"
    valid_file.write_text(
        'message = "database connection failed"\n',
        encoding="utf-8",
    )

    original_resolve = Path.resolve

    def resolve_candidate(self, *args, **kwargs):
        if self == unresolvable_file:
            raise OSError("Unable to resolve candidate")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_candidate)
    monkeypatch.setattr(source_code_analyzer, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        source_code_analyzer,
        "SOURCE_DIRECTORY",
        source_directory,
    )

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
        "endpoint": "",
    }

    results = search_source_code(incident)

    assert [result["file"] for result in results] == ["app\\valid.py"]
