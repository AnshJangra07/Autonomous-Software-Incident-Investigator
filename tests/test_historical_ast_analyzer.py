from pathlib import Path

import git
import pytest

from app.services import historical_ast_analyzer
from app.services.historical_ast_analyzer import analyze_historical_functions


def _create_repository(
    repo_path: Path,
    file_path: str,
    source: str,
) -> tuple[git.Repo, str]:
    repo_path.mkdir()
    repository = git.Repo.init(repo_path)

    with repository.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")

    source_file = repo_path / file_path
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(source.encode("utf-8"))
    repository.index.add([file_path])
    commit = repository.index.commit("Add historical source")
    return repository, commit.hexsha


def _configure_reader_root(monkeypatch, repo_path):
    monkeypatch.setattr(
        "app.services.git_source_reader.PROJECT_ROOT",
        repo_path,
    )


def test_uses_function_boundaries_from_historical_commit(
    tmp_path,
    monkeypatch,
):
    repo_path = tmp_path / "repo"
    repository, commit_hash = _create_repository(
        repo_path,
        "app/example.py",
        "def historical_function():\n"
        "    return 'committed'\n",
    )
    (repo_path / "app" / "example.py").write_text(
        "def working_tree_function():\n"
        "    return 'current'\n"
        "\n"
        "def another_working_tree_function():\n"
        "    return 'current too'\n",
        encoding="utf-8",
    )
    _configure_reader_root(monkeypatch, repo_path)

    result = analyze_historical_functions(commit_hash, "app/example.py")

    assert result == {
        "commit_hash": commit_hash,
        "file_path": "app/example.py",
        "functions": [{
            "function_name": "historical_function",
            "start_line": 1,
            "end_line": 2,
            "is_async": False,
        }],
        "status": "available",
    }
    assert repository.is_dirty()


def test_extracts_nested_functions_methods_and_async_metadata(
    tmp_path,
    monkeypatch,
):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        "app/service.py",
        "class Service:\n"
        "    def outer(self):\n"
        "        async def inner():\n"
        "            return True\n"
        "        return inner()\n",
    )
    _configure_reader_root(monkeypatch, repo_path)

    result = analyze_historical_functions(commit_hash, "app/service.py")

    assert result["status"] == "available"
    assert result["functions"] == [
        {
            "function_name": "outer",
            "start_line": 2,
            "end_line": 5,
            "is_async": False,
        },
        {
            "function_name": "inner",
            "start_line": 3,
            "end_line": 4,
            "is_async": True,
        },
    ]


def test_missing_historical_file_returns_not_found(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        "app/example.py",
        "value = 1\n",
    )
    _configure_reader_root(monkeypatch, repo_path)

    result = analyze_historical_functions(commit_hash, "app/missing.py")

    assert result["status"] == "not_found"
    assert result["functions"] == []
    assert result["commit_hash"] == commit_hash
    assert result["file_path"] == "app/missing.py"


def test_invalid_commit_returns_not_found(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _create_repository(repo_path, "app/example.py", "value = 1\n")
    _configure_reader_root(monkeypatch, repo_path)

    result = analyze_historical_functions("not-a-commit", "app/example.py")

    assert result["status"] == "not_found"
    assert result["functions"] == []


def test_invalid_source_syntax_returns_invalid_source(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        "app/invalid.py",
        "def broken_function(:\n    pass\n",
    )
    _configure_reader_root(monkeypatch, repo_path)

    result = analyze_historical_functions(commit_hash, "app/invalid.py")

    assert result["status"] == "invalid_source"
    assert result["functions"] == []
    assert result["error_reason"] == (
        "Historical source has invalid Python syntax."
    )


@pytest.mark.parametrize(
    ("source_status", "expected_status"),
    [
        ("unavailable", "unavailable"),
        ("invalid_input", "invalid_input"),
        ("not_found", "not_found"),
    ],
)
def test_propagates_historical_source_status(
    monkeypatch,
    source_status,
    expected_status,
):
    monkeypatch.setattr(
        historical_ast_analyzer,
        "get_file_content_at_commit",
        lambda commit_hash, file_path: {
            "commit_hash": commit_hash,
            "file_path": file_path,
            "content": None,
            "status": source_status,
            "error_reason": "Source lookup failed.",
        },
    )

    result = analyze_historical_functions("abc123", "app/example.py")

    assert result["status"] == expected_status
    assert result["functions"] == []
    assert result["error_reason"] == "Source lookup failed."


def test_rejects_invalid_inputs(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _create_repository(repo_path, "app/example.py", "value = 1\n")
    _configure_reader_root(monkeypatch, repo_path)

    result = analyze_historical_functions("", "app/example.py")

    assert result["status"] == "invalid_input"
    assert result["functions"] == []
    assert result["error_reason"] == (
        "commit_hash must be a non-empty string."
    )


def test_does_not_depend_on_the_project_working_tree(monkeypatch):
    monkeypatch.setattr(
        historical_ast_analyzer,
        "get_file_content_at_commit",
        lambda commit_hash, file_path: {
            "commit_hash": commit_hash,
            "file_path": file_path,
            "content": "def from_commit():\n    pass\n",
            "content_available": True,
            "status": "available",
        },
    )
    monkeypatch.setattr(
        "app.services.ast_code_analyzer.extract_functions",
        lambda file_path: pytest.fail("Working-tree AST reader was called"),
    )

    result = analyze_historical_functions("abc123", "app/example.py")

    assert result["status"] == "available"
    assert result["functions"][0]["function_name"] == "from_commit"

