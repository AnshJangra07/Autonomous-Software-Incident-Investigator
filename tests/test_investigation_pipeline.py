from pathlib import Path

import git
import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from git.exc import (
    BadName,
    BadObject,
    GitCommandError,
    InvalidGitRepositoryError,
)

from app.schemas import InvestigationReport
from app.services.investigation_pipeline import (
    _analyze_commit_changes,
    calculate_recency_score,
    investigate_incident,
)


def _schema_source_evidence(entries, file_path="app/services/database.py"):
    normalized_entries = []
    for entry in entries:
        line_number = entry.get("line_number", 1)
        normalized = {
            "file": file_path,
            "line_number": line_number,
            "matching_keywords": [],
            "relevance_score": 1,
            "code_snippet": "",
            "start_line": max(1, line_number - 2),
            "end_line": line_number + 2,
            "context": "",
            "function": None,
        }
        normalized.update(entry)
        if isinstance(normalized["function"], dict):
            function = {"is_async": False}
            function.update(normalized["function"])
            normalized["function"] = function
        normalized_entries.append(normalized)
    return normalized_entries


def _schema_git_history(entries, file_path):
    normalized_entries = []
    for entry in entries:
        commit_hash = entry.get("commit_hash", "")
        normalized = {
            "commit_hash": commit_hash,
            "short_hash": commit_hash[:8],
            "author": "Test Author",
            "date": "",
            "message": "",
            "changed_files": [file_path],
        }
        normalized.update(entry)
        normalized_entries.append(normalized)
    return normalized_entries


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
    assert isinstance(InvestigationReport.model_validate(report), InvestigationReport)


def test_empty_source_evidence_returns_a_valid_report():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=[],
    ):
        report = investigate_incident(incident)

    validated_report = InvestigationReport.model_validate(report)

    assert report["investigation_status"] == "no_source_evidence"
    assert report["source_evidence"] == []
    assert report["git_history"] == {}
    assert validated_report.statistics.source_matches == 0


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
    assert report["statistics"]["commits_found"] == sum(
        len(commits) for commits in report["git_history"].values()
    )
    assert (
        report["statistics"]["potentially_relevant_commits"]
        == len(report["potentially_relevant_commits"])
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


def test_maximum_pipeline_limits_are_accepted():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }
    source_results = _schema_source_evidence(
        [{"line_number": 10}],
        file_path="app/services/database.py",
    )

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_results,
    ) as search_source, patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=[],
    ) as get_history:
        investigate_incident(
            incident,
            max_source_results=50,
            max_commits_per_file=50,
        )

    search_source.assert_called_once_with(incident, max_results=50)
    get_history.assert_called_once_with(
        "app/services/database.py",
        max_commits=50,
    )


@pytest.mark.parametrize(
    ("parameter", "value", "message"),
    [
        ("max_source_results", 51, "max_source_results must not exceed 50"),
        (
            "max_commits_per_file",
            51,
            "max_commits_per_file must not exceed 50",
        ),
    ],
)
def test_pipeline_limits_above_maximum_are_rejected(
    parameter,
    value,
    message,
):
    with pytest.raises(ValueError, match=message):
        investigate_incident(
            {"failure_type": "database"},
            **{parameter: value},
        )


@pytest.mark.parametrize(
    ("parameter", "value", "error"),
    [
        ("max_source_results", 0, ValueError),
        ("max_source_results", True, TypeError),
        ("max_commits_per_file", True, TypeError),
    ],
)
def test_pipeline_invalid_limit_values_are_rejected(parameter, value, error):
    with pytest.raises(error):
        investigate_incident(
            {"failure_type": "database"},
            **{parameter: value},
        )


def test_default_pipeline_limits_are_preserved():
    incident = {"failure_type": "database"}
    source_results = _schema_source_evidence(
        [{"line_number": 10}],
        file_path="app/services/database.py",
    )

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_results,
    ) as search_source, patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=[],
    ) as get_history:
        investigate_incident(incident)

    search_source.assert_called_once_with(incident, max_results=10)
    get_history.assert_called_once_with(
        "app/services/database.py",
        max_commits=5,
    )



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
        side_effect=lambda *args, **kwargs: _schema_source_evidence(
            source_evidence
        ),
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=lambda file_path, **kwargs: _schema_git_history(
            git_history,
            file_path,
        ),
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ):
        report = investigate_incident(incident)

    matches = report["potentially_relevant_commits"]

    assert len(matches) == 1
    assert matches[0]["commit_hash"] == "abc123"
    assert "database" in matches[0]["matching_keywords"]
    assert report["statistics"]["potentially_relevant_commits"] == 1
    assert report["diagnosis"]["root_cause_confirmed"] is False
    assert matches[0]["relevance_score"] > 0
    assert matches[0]["change_evidence"]["added_lines"] == []


def test_missing_source_file_does_not_block_other_file_history(
    tmp_path,
    monkeypatch,
):
    missing_file = "app/services/a_missing.py"
    valid_file = "app/services/z_valid.py"
    valid_source_path = tmp_path / "app" / "services" / "z_valid.py"
    valid_source_path.parent.mkdir(parents=True)
    valid_source_path.write_text("value = True\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.investigation_pipeline.PROJECT_ROOT",
        tmp_path,
    )
    source_evidence = _schema_source_evidence([
        {"file": missing_file, "line_number": 2},
        {"file": valid_file, "line_number": 3},
    ])

    def history_for_file(file_path, max_commits):
        if file_path == missing_file:
            raise ValueError(
                "Only existing Python files inside app/ are allowed"
            )
        return _schema_git_history([{
            "commit_hash": "valid123",
            "message": "Database connection update",
        }], file_path)

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_evidence,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=history_for_file,
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        return_value={
            "functions": [],
            "status": "available",
        },
    ), patch(
        "app.services.investigation_pipeline._is_current_head_commit",
        return_value=False,
    ):
        report = investigate_incident({
            "failure_type": "database",
            "message": "Database connection failed",
        })

    assert report["git_history"][missing_file] == []
    assert report["git_history"][valid_file][0]["commit_hash"] == "valid123"
    assert report["statistics"]["source_matches"] == 2
    assert report["statistics"]["files_investigated"] == 2
    assert report["statistics"]["commits_found"] == 1
    assert [candidate["file"] for candidate in (
        report["potentially_relevant_commits"]
    )] == [valid_file]


def test_unexpected_history_value_error_still_propagates():
    source_evidence = _schema_source_evidence([
        {"file": "app/services/database.py", "line_number": 2},
    ])

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_evidence,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=ValueError("unexpected history programming error"),
    ):
        with pytest.raises(
            ValueError,
            match="unexpected history programming error",
        ):
            investigate_incident({
                "failure_type": "database",
                "message": "Database connection failed",
            })


def test_missing_commit_hash_skips_only_malformed_history_entry():
    file_path = "app/services/database.py"
    source_evidence = _schema_source_evidence([{
        "file": file_path,
        "line_number": 2,
    }])
    malformed_entry = {
        "short_hash": "missing",
        "author": "Test Author",
        "date": "",
        "message": "Database connection failure",
        "changed_files": [file_path],
    }
    valid_entry = _schema_git_history([{
        "commit_hash": "valid123",
        "message": "Database connection update",
    }], file_path)[0]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_evidence,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=[malformed_entry, valid_entry],
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        return_value={"functions": [], "status": "available"},
    ), patch(
        "app.services.investigation_pipeline._is_current_head_commit",
        return_value=False,
    ):
        report = investigate_incident({
            "failure_type": "database",
            "message": "Database connection failed",
        })

    assert [
        entry["commit_hash"]
        for entry in report["git_history"][file_path]
    ] == ["valid123"]
    assert [
        candidate["commit_hash"]
        for candidate in report["potentially_relevant_commits"]
    ] == ["valid123"]


def test_missing_source_fields_skip_bad_record_and_preserve_valid_evidence():
    valid_path = "app/services/valid_database.py"
    source_results = [
        {"file": "app/services/incomplete.py"},
        *_schema_source_evidence([{
            "file": valid_path,
            "line_number": 2,
        }]),
    ]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_results,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=[],
    ) as get_file_commit_history:
        report = investigate_incident({
            "failure_type": "database",
            "message": "Database connection failed",
        })

    assert len(report["source_evidence"]) == 1
    assert report["source_evidence"][0]["file"] == valid_path
    get_file_commit_history.assert_called_once_with(
        valid_path,
        max_commits=5,
    )


def test_non_list_source_evidence_result_fails_explicitly():
    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value={"file": "app/services/database.py"},
    ):
        with pytest.raises(
            TypeError,
            match="search_source_code must return a list",
        ):
            investigate_incident({
                "failure_type": "database",
                "message": "Database connection failed",
            })


def test_non_list_history_result_isolated_from_other_files():
    invalid_path = "app/services/a_invalid_history.py"
    valid_path = "app/services/z_valid_history.py"
    source_evidence = _schema_source_evidence([
        {"file": invalid_path, "line_number": 2},
        {"file": valid_path, "line_number": 3},
    ])
    valid_history = _schema_git_history([{
        "commit_hash": "valid123",
        "message": "Database connection update",
    }], valid_path)

    def history_for_file(file_path, max_commits):
        if file_path == invalid_path:
            return {"unexpected": "mapping"}
        return valid_history

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=source_evidence,
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=history_for_file,
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        return_value={"functions": [], "status": "available"},
    ), patch(
        "app.services.investigation_pipeline._is_current_head_commit",
        return_value=False,
    ):
        report = investigate_incident({
            "failure_type": "database",
            "message": "Database connection failed",
        })

    assert report["git_history"][invalid_path] == []
    assert report["git_history"][valid_path] == valid_history
    assert [
        candidate["file"]
        for candidate in report["potentially_relevant_commits"]
    ] == [valid_path]


@pytest.mark.parametrize(
    ("ast_result", "expected_status", "expected_error"),
    [
        (None, "unavailable", "Historical AST result is unavailable."),
        (
            {"status": "available", "functions": {}},
            "unavailable",
            "Historical function data is unavailable.",
        ),
        (
            {
                "status": "available",
                "functions": [{
                    "function_name": "broken_function",
                    "start_line": 0,
                    "end_line": 3,
                    "is_async": False,
                }],
            },
            "unavailable",
            "Historical function data is malformed.",
        ),
    ],
)
def test_malformed_historical_ast_results_are_unavailable(
    ast_result,
    expected_status,
    expected_error,
):
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        return_value=ast_result,
    ), patch(
        "app.services.investigation_pipeline._is_current_head_commit",
        return_value=False,
    ):
        evidence = _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )

    assert evidence["historical_ast_status"] == expected_status
    assert evidence["historical_ast_error_reason"] == expected_error


def test_valid_historical_functions_are_preserved_with_malformed_sibling():
    valid_function = {
        "function_name": "valid_function",
        "start_line": 1,
        "end_line": 3,
        "is_async": False,
    }
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={
            "diff_found": True,
            "patch": "@@ -1 +1,2 @@\n context\n+new_line\n",
        },
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        return_value={
            "status": "available",
            "functions": [
                valid_function,
                {"function_name": "malformed", "start_line": "bad"},
            ],
        },
    ), patch(
        "app.services.investigation_pipeline._is_current_head_commit",
        return_value=False,
    ):
        evidence = _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )

    assert evidence["matching_added_function_names"] == ["valid_function"]
    assert evidence["historical_ast_status"] == "available"
    assert evidence["historical_ast_error_reason"] == (
        "Some historical function data was malformed and ignored."
    )


def test_unexpected_source_search_exception_still_propagates():
    with patch(
        "app.services.investigation_pipeline.search_source_code",
        side_effect=RuntimeError("source service failure"),
    ):
        with pytest.raises(RuntimeError, match="source service failure"):
            investigate_incident({
                "failure_type": "database",
                "message": "Database connection failed",
            })


def test_unexpected_historical_ast_exception_still_propagates():
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        side_effect=RuntimeError("historical AST service failure"),
    ):
        with pytest.raises(
            RuntimeError,
            match="historical AST service failure",
        ):
            _analyze_commit_changes(
                "app/services/database.py",
                "abc123",
                [],
            )


def _investigate_with_changes(
    source_evidence,
    diff_result,
    historical_functions=None,
    is_head_commit=False,
):
    if historical_functions is None:
        historical_functions = []

    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }
    git_history = [{
        "commit_hash": "abc123",
        "message": "Database connection failed",
    }]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        side_effect=lambda *args, **kwargs: _schema_source_evidence(
            source_evidence
        ),
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=lambda file_path, **kwargs: _schema_git_history(
            git_history,
            file_path,
        ),
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value=diff_result,
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        side_effect=lambda commit_hash, file_path: {
            "commit_hash": commit_hash,
            "file_path": file_path,
            "functions": historical_functions,
            "status": "available",
        },
    ), patch(
        "app.services.investigation_pipeline._get_parent_commit_hash",
        return_value="parent123",
    ), patch(
        "app.services.investigation_pipeline._is_current_head_commit",
        return_value=is_head_commit,
    ):
        return investigate_incident(incident)


def _change_evidence(report):
    return report["potentially_relevant_commits"][0]["change_evidence"]


def _analyze_diff_result(diff_result):
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value=diff_result,
    ):
        return _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )


@pytest.mark.parametrize(
    ("diff_result", "expected_status", "has_error_reason"),
    [
        (None, "unavailable", True),
        ({}, "unavailable", True),
        ({"diff_found": False}, "unavailable", True),
        ({"patch": ""}, "unavailable", True),
        (
            {"diff_found": False, "patch": "unexpected patch"},
            "invalid_diff",
            True,
        ),
        ({"diff_found": False, "patch": ""}, "no_diff", False),
        ({"diff_found": True}, "unavailable", True),
        ({"diff_found": True, "patch": None}, "invalid_diff", True),
        ({"diff_found": True, "patch": 123}, "invalid_diff", True),
        ({"diff_found": "yes", "patch": ""}, "unavailable", True),
        ({"diff_found": True, "patch": ""}, "no_diff", False),
    ],
)
def test_classifies_missing_unexpected_and_empty_diff_results(
    diff_result,
    expected_status,
    has_error_reason,
):
    evidence = _analyze_diff_result(diff_result)

    assert evidence["status"] == expected_status
    assert ("error_reason" in evidence) is has_error_reason
    if has_error_reason:
        assert evidence["error_reason"]


@pytest.mark.parametrize(
    "parse_error",
    [
        ValueError("private parser detail"),
        TypeError("private parser detail"),
    ],
)
def test_parser_errors_return_invalid_diff_without_internal_details(parse_error):
    diff_result = {"diff_found": True, "patch": "@@ -1 +1 @@\n+new\n"}
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value=diff_result,
    ), patch(
        "app.services.investigation_pipeline.extract_changed_lines",
        side_effect=parse_error,
    ):
        evidence = _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )

    assert evidence["status"] == "invalid_diff"
    assert evidence["error_reason"] == "Git patch could not be parsed."
    assert "private parser detail" not in evidence["error_reason"]


def test_malformed_patch_returns_invalid_diff():
    evidence = _analyze_diff_result({
        "diff_found": True,
        "patch": "@@ malformed @@\n+new\n",
    })

    assert evidence["status"] == "invalid_diff"
    assert evidence["error_reason"] == "Git patch could not be parsed."


@pytest.mark.parametrize(
    "git_error",
    [
        GitCommandError("git diff", 1),
        InvalidGitRepositoryError("private repository path"),
        BadObject("private object id"),
        BadName("private commit name"),
    ],
)
def test_expected_git_retrieval_errors_return_unavailable(git_error):
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        side_effect=git_error,
    ):
        evidence = _analyze_commit_changes(
            "app/services/database.py",
            "abc123",
            [],
        )

    assert evidence["status"] == "unavailable"
    assert evidence["error_reason"] == "Git diff could not be retrieved."
    assert "private" not in evidence["error_reason"]


def test_unexpected_programming_error_from_diff_retrieval_is_not_hidden():
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        side_effect=RuntimeError("unexpected programming error"),
    ):
        with pytest.raises(RuntimeError, match="unexpected programming error"):
            _analyze_commit_changes(
                "app/services/database.py",
                "abc123",
                [],
            )


@pytest.mark.parametrize(
    ("is_head_commit", "expected_status", "expected_overlap"),
    [
        (True, "available", True),
        (False, "unavailable", False),
    ],
)
def test_source_evidence_overlap_requires_current_head(
    is_head_commit,
    expected_status,
    expected_overlap,
):
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 10,
            "function": None,
        }],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+changed line\n",
        },
        is_head_commit=is_head_commit,
    )

    evidence = _change_evidence(report)

    assert evidence["source_evidence_overlap_status"] == expected_status
    assert evidence["overlaps_suspicious_source_evidence"] is expected_overlap
    if not is_head_commit:
        assert evidence["source_evidence_overlap_error_reason"] == (
            "Source evidence is from the current working tree and does not "
            "match this commit."
        )
    assert evidence["added_lines"] == [
        {"line_number": 10, "content": "changed line"},
    ]


def _create_source_repository(tmp_path, source):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repository = git.Repo.init(repo_path)

    with repository.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")

    working_file = repo_path / "app" / "example.py"
    working_file.parent.mkdir(parents=True)
    working_file.write_bytes(source.encode("utf-8"))
    repository.index.add(["app/example.py"])
    commit = repository.index.commit("Add source")
    return repo_path, repository, working_file, commit


def _analyze_source_overlap(
    monkeypatch,
    repo_path,
    commit_hash,
    source_evidence,
):
    monkeypatch.setattr(
        "app.services.investigation_pipeline.PROJECT_ROOT",
        repo_path,
    )
    monkeypatch.setattr(
        "app.services.git_source_reader.PROJECT_ROOT",
        repo_path,
    )
    with patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={
            "diff_found": True,
            "patch": (
                "@@ -1,1 +1,2 @@\n"
                " def current_function():\n"
                "+    return False\n"
            ),
        },
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        side_effect=lambda requested_commit, requested_file: {
            "commit_hash": requested_commit,
            "file_path": requested_file,
            "functions": [],
            "status": "available",
        },
    ):
        return _analyze_commit_changes(
            "app/example.py",
            commit_hash,
            source_evidence,
        )


def test_head_with_unchanged_working_file_allows_source_overlap(
    tmp_path,
    monkeypatch,
):
    repo_path, _, _, commit = _create_source_repository(
        tmp_path,
        "def current_function():\n    return True\n",
    )

    evidence = _analyze_source_overlap(
        monkeypatch,
        repo_path,
        commit.hexsha,
        [{"file": "app/example.py", "line_number": 2}],
    )

    assert evidence["source_evidence_overlap_status"] == "available"
    assert evidence["overlaps_suspicious_source_evidence"] is True


def test_head_with_modified_working_file_disables_source_overlap(
    tmp_path,
    monkeypatch,
):
    repo_path, _, working_file, commit = _create_source_repository(
        tmp_path,
        "def current_function():\n    return True\n",
    )
    working_file.write_text(
        "def current_function():\n    return 'uncommitted'\n",
        encoding="utf-8",
    )

    evidence = _analyze_source_overlap(
        monkeypatch,
        repo_path,
        commit.hexsha,
        [{"file": "app/example.py", "line_number": 2}],
    )

    assert evidence["source_evidence_overlap_status"] == "unavailable"
    assert evidence["overlaps_suspicious_source_evidence"] is False


def test_non_head_commit_disables_source_overlap(tmp_path, monkeypatch):
    repo_path, repository, working_file, old_commit = _create_source_repository(
        tmp_path,
        "def old_function():\n    return True\n",
    )
    working_file.write_bytes(
        b"def current_function():\n    return True\n"
    )
    repository.index.add(["app/example.py"])
    repository.index.commit("Update source")

    evidence = _analyze_source_overlap(
        monkeypatch,
        repo_path,
        old_commit.hexsha,
        [{"file": "app/example.py", "line_number": 2}],
    )

    assert evidence["source_evidence_overlap_status"] == "unavailable"
    assert evidence["overlaps_suspicious_source_evidence"] is False


@pytest.mark.parametrize("file_problem", ["missing", "unreadable"])
def test_unavailable_working_file_disables_source_overlap(
    tmp_path,
    monkeypatch,
    file_problem,
):
    repo_path, _, working_file, commit = _create_source_repository(
        tmp_path,
        "def current_function():\n    return True\n",
    )

    if file_problem == "missing":
        working_file.unlink()
    else:
        original_read_bytes = Path.read_bytes

        def raise_for_source_file(path):
            if path == working_file:
                raise PermissionError("unreadable source")
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", raise_for_source_file)

    evidence = _analyze_source_overlap(
        monkeypatch,
        repo_path,
        commit.hexsha,
        [{"file": "app/example.py", "line_number": 2}],
    )

    assert evidence["source_evidence_overlap_status"] == "unavailable"
    assert evidence["overlaps_suspicious_source_evidence"] is False


def test_historical_boundaries_override_current_function_evidence():
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 5,
            "function": {
                "function_name": "current_connect_database",
                "start_line": 4,
                "end_line": 6,
            },
        }],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+changed line\n",
        },
        historical_functions=[{
            "function_name": "historical_connect_database",
            "start_line": 8,
            "end_line": 12,
            "is_async": False,
        }],
    )

    evidence = _change_evidence(report)

    assert evidence["overlaps_suspicious_source_evidence"] is False
    assert evidence["added_lines_overlap_historical_function"] is True
    assert evidence["matching_function_names"] == [
        "historical_connect_database",
    ]
    assert evidence["matching_added_function_names"] == [
        "historical_connect_database",
    ]


def test_deleted_line_uses_parent_historical_function_boundaries():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }
    source_evidence = [{
        "file": "app/services/database.py",
        "line_number": 20,
        "function": None,
    }]
    git_history = [{
        "commit_hash": "abc123",
        "message": "Database connection failed",
    }]

    def historical_result(commit_hash, file_path):
        if commit_hash == "parent123":
            functions = [{
                "function_name": "deleted_function",
                "start_line": 10,
                "end_line": 12,
                "is_async": False,
            }]
        else:
            functions = [{
                "function_name": "current_function",
                "start_line": 1,
                "end_line": 3,
                "is_async": False,
            }]
        return {
            "commit_hash": commit_hash,
            "file_path": file_path,
            "functions": functions,
            "status": "available",
        }

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        side_effect=lambda *args, **kwargs: _schema_source_evidence(
            source_evidence
        ),
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=lambda file_path, **kwargs: _schema_git_history(
            git_history,
            file_path,
        ),
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={
            "diff_found": True,
            "patch": "@@ -10 +9,0 @@\n-deleted line\n",
        },
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        side_effect=historical_result,
    ), patch(
        "app.services.investigation_pipeline._get_parent_commit_hash",
        return_value="parent123",
    ):
        report = investigate_incident(incident)

    evidence = _change_evidence(report)

    assert evidence["deleted_line_function_matches"] == [{
        "line_number": 10,
        "function_names": ["deleted_function"],
    }]
    assert evidence["matching_deleted_function_names"] == [
        "deleted_function",
    ]
    assert evidence["matching_function_names"] == ["deleted_function"]
    assert evidence["deleted_historical_ast_status"] == "available"


def test_added_line_outside_suspicious_functions():
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 5,
            "function": {
                "function_name": "connect_database",
                "start_line": 4,
                "end_line": 6,
            },
        }],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+changed line\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["overlaps_suspicious_source_evidence"] is False
    assert evidence["matching_function_names"] == []


def test_commit_with_no_diff_has_empty_change_evidence():
    report = _investigate_with_changes(
        [{"file": "app/services/database.py", "line_number": 10}],
        {"diff_found": False, "patch": ""},
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "no_diff"
    assert evidence["added_lines"] == []
    assert evidence["deleted_lines"] == []
    assert evidence["overlaps_suspicious_source_evidence"] is False


def test_commit_with_no_added_lines_only_reports_deletions():
    report = _investigate_with_changes(
        [{"file": "app/services/database.py", "line_number": 10}],
        {
            "diff_found": True,
            "patch": "@@ -10 +9,0 @@\n-deleted line\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "available"
    assert evidence["added_lines"] == []
    assert evidence["deleted_lines"] == [
        {"line_number": 10, "content": "deleted line"},
    ]
    assert evidence["overlaps_suspicious_source_evidence"] is False


def test_missing_diff_result_is_handled_as_empty_evidence():
    report = _investigate_with_changes(
        [{"file": "app/services/database.py", "line_number": 10}],
        None,
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "unavailable"
    assert evidence["error_reason"] == (
        "Git diff result was missing or unusable."
    )
    assert evidence["added_lines"] == []
    assert evidence["deleted_lines"] == []
    assert "historical_ast_error_reason" not in evidence
    assert "deleted_historical_ast_error_reason" not in evidence


def test_multiple_added_lines_are_correlated_with_evidence_and_functions():
    report = _investigate_with_changes(
        [{
            "file": "app/services/database.py",
            "line_number": 11,
            "function": {
                "function_name": "connect_database",
                "start_line": 10,
                "end_line": 11,
            },
        }],
        {
            "diff_found": True,
            "patch": (
                "@@ -4,1 +4,3 @@\n context\n+first\n+second\n"
            ),
        },
        historical_functions=[
            {
                "function_name": "first_function",
                "start_line": 5,
                "end_line": 5,
                "is_async": False,
            },
            {
                "function_name": "second_function",
                "start_line": 6,
                "end_line": 6,
                "is_async": False,
            },
        ],
    )

    evidence = _change_evidence(report)

    assert evidence["added_lines"] == [
        {"line_number": 5, "content": "first"},
        {"line_number": 6, "content": "second"},
    ]
    assert evidence["added_line_function_matches"] == [
        {"line_number": 5, "function_names": ["first_function"]},
        {"line_number": 6, "function_names": ["second_function"]},
    ]
    assert evidence["matching_added_function_names"] == [
        "first_function",
        "second_function",
    ]
    assert evidence["overlaps_suspicious_source_evidence"] is False
    assert evidence["added_lines_overlap_historical_function"] is True
    assert evidence["matching_function_names"] == [
        "first_function",
        "second_function",
    ]
    assert "does not prove causality" in evidence["note"]


@pytest.mark.parametrize("ast_status", ["unavailable", "invalid_source"])
def test_ast_failure_preserves_diff_evidence(ast_status):
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }
    git_history = [{
        "commit_hash": "abc123",
        "message": "Database connection failed",
    }]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=_schema_source_evidence([
            {"file": "app/services/database.py"},
        ]),
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=lambda file_path, **kwargs: _schema_git_history(
            git_history,
            file_path,
        ),
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+changed line\n",
        },
    ), patch(
        "app.services.investigation_pipeline.analyze_historical_functions",
        return_value={
            "commit_hash": "abc123",
            "file_path": "app/services/database.py",
            "functions": [],
            "status": ast_status,
            "error_reason": "Historical AST unavailable.",
        },
    ):
        report = investigate_incident(incident)

    evidence = _change_evidence(report)

    assert evidence["status"] == "available"
    assert evidence["added_lines"] == [
        {"line_number": 10, "content": "changed line"},
    ]
    assert evidence["historical_ast_status"] == ast_status
    assert evidence["historical_ast_error_reason"] == (
        "Historical AST unavailable."
    )
    assert evidence["matching_function_names"] == []


def test_file_with_no_functions_has_empty_function_correlation():
    report = _investigate_with_changes(
        [{"file": "app/services/database.py", "line_number": 10}],
        {
            "diff_found": True,
            "patch": "@@ -9 +9,2 @@\n context\n+module_value = True\n",
        },
    )

    evidence = _change_evidence(report)

    assert evidence["status"] == "available"
    assert evidence["added_line_function_matches"] == [{
        "line_number": 10,
        "function_names": [],
    }]
    assert evidence["matching_function_names"] == []
    assert evidence["added_lines_overlap_historical_function"] is False


def test_change_evidence_preserves_existing_candidate_scoring_and_fields():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }
    source_evidence = [{
        "file": "app/services/database.py",
        "line_number": 10,
        "relevance_score": 8,
        "function": None,
    }]
    git_history = [{
        "commit_hash": "abc123",
        "message": "Database connection failed",
    }]

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        side_effect=lambda *args, **kwargs: _schema_source_evidence(
            source_evidence
        ),
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        side_effect=lambda file_path, **kwargs: _schema_git_history(
            git_history,
            file_path,
        ),
    ), patch(
        "app.services.investigation_pipeline.get_commit_diff",
        return_value={"diff_found": False, "patch": ""},
    ) as get_commit_diff, patch(
        "app.services.investigation_pipeline.calculate_recency_score",
        return_value=0.5,
    ):
        report = investigate_incident(incident)

    candidate = report["potentially_relevant_commits"][0]

    get_commit_diff.assert_called_once_with(
        "abc123",
        "app/services/database.py",
    )
    assert candidate["relevance_score"] == 0.84
    assert candidate["file"] == "app/services/database.py"
    assert candidate["commit_hash"] == "abc123"
    assert candidate["message"] == "Database connection failed"
    assert candidate["matching_keywords"] == [
        "connection",
        "database",
        "failed",
    ]
    assert candidate["change_evidence"]["file_path"] == candidate["file"]
    assert report["source_evidence"][0]["function"] is None


def test_no_commit_matches_returns_empty_list():
    incident = {
        "failure_type": "database",
        "message": "Database connection failed",
    }

    with patch(
        "app.services.investigation_pipeline.search_source_code",
        return_value=_schema_source_evidence([
            {"file": "app/services/database.py"},
        ]),
    ), patch(
        "app.services.investigation_pipeline.get_file_commit_history",
        return_value=_schema_git_history(
            [{
                "commit_hash": "xyz123",
                "message": "Update frontend styling",
            }],
            "app/services/database.py",
        ),
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