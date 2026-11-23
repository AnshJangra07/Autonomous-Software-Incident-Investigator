from pathlib import Path

import git
import pytest

from app.services import git_source_reader
from app.services.git_source_reader import get_file_content_at_commit


def _create_repository(
    repo_path: Path,
    files: dict[str, bytes | str],
) -> tuple[git.Repo, str]:
    repo_path.mkdir()
    repository = git.Repo.init(repo_path)

    with repository.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")

    for relative_path, content in files.items():
        source_file = repo_path / relative_path
        source_file.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            source_file.write_bytes(content)
        else:
            source_file.write_bytes(content.encode("utf-8"))

    repository.index.add(list(files))
    commit = repository.index.commit("Add source files")
    return repository, commit.hexsha


def _read_from_repository(monkeypatch, repo_path, commit_hash, file_path):
    monkeypatch.setattr(git_source_reader, "PROJECT_ROOT", repo_path)
    return get_file_content_at_commit(commit_hash, file_path)


def test_reads_file_content_from_commit_without_using_working_tree(
    tmp_path,
    monkeypatch,
):
    repo_path = tmp_path / "repo"
    repository, commit_hash = _create_repository(
        repo_path,
        {"app/example.py": "committed_value = 1\n"},
    )
    working_file = repo_path / "app" / "example.py"
    working_file.write_text("working_tree_value = 2\n", encoding="utf-8")

    result = _read_from_repository(
        monkeypatch,
        repo_path,
        commit_hash,
        "app/example.py",
    )

    assert result == {
        "commit_hash": commit_hash,
        "file_path": "app/example.py",
        "content": "committed_value = 1\n",
        "content_available": True,
        "status": "available",
    }
    assert working_file.read_text(encoding="utf-8") == "working_tree_value = 2\n"
    assert repository.is_dirty()


@pytest.mark.parametrize(
    ("commit_hash", "file_path", "reason"),
    [
        ("", "app/example.py", "commit_hash"),
        (None, "app/example.py", "commit_hash"),
        (123, "app/example.py", "commit_hash"),
        ("abc123", "", "file_path"),
        ("abc123", None, "file_path"),
        ("abc123", 123, "file_path"),
        ("abc123", "README.md", "Only Python files"),
        ("abc123", "../outside.py", "inside the project"),
        ("abc123", "app/../outside.py", "inside the project"),
    ],
)
def test_rejects_invalid_inputs(
    tmp_path,
    monkeypatch,
    commit_hash,
    file_path,
    reason,
):
    repo_path = tmp_path / "repo"
    _create_repository(repo_path, {"app/example.py": "value = 1\n"})

    result = _read_from_repository(
        monkeypatch,
        repo_path,
        commit_hash,
        file_path,
    )

    assert result["status"] == "invalid_input"
    assert result["content"] is None
    assert result["content_available"] is False
    assert reason in result["error_reason"]


def test_rejects_absolute_paths_without_echoing_them(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        {"app/example.py": "value = 1\n"},
    )
    absolute_path = str(repo_path / "app" / "example.py")

    result = _read_from_repository(
        monkeypatch,
        repo_path,
        commit_hash,
        absolute_path,
    )

    assert result["status"] == "invalid_input"
    assert result["file_path"] == ""
    assert absolute_path not in result["error_reason"]


def test_invalid_commit_hash_returns_not_found(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _create_repository(repo_path, {"app/example.py": "value = 1\n"})

    result = _read_from_repository(
        monkeypatch,
        repo_path,
        "not-a-commit",
        "app/example.py",
    )

    assert result["status"] == "not_found"
    assert result["content"] is None
    assert result["error_reason"] == "Commit was not found."


def test_missing_file_returns_not_found(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        {"app/example.py": "value = 1\n"},
    )

    result = _read_from_repository(
        monkeypatch,
        repo_path,
        commit_hash,
        "app/missing.py",
    )

    assert result["status"] == "not_found"
    assert result["content_available"] is False


def test_directory_in_commit_is_not_returned_as_a_file(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        {"app/folder.py/child.txt": "not a Python file\n"},
    )

    result = _read_from_repository(
        monkeypatch,
        repo_path,
        commit_hash,
        "app/folder.py",
    )

    assert result["status"] == "not_found"
    assert result["error_reason"] == "File was not found in the commit."


def test_symbolic_link_blob_is_not_returned_as_source(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repository = git.Repo.init(repo_path)

    with repository.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")

    (repo_path / "app").mkdir()
    target_path = repo_path / "target"
    target_path.write_text("target.py", encoding="utf-8")
    target_blob = repository.git.hash_object("-w", str(target_path))
    repository.git.update_index(
        "--add",
        "--cacheinfo",
        f"120000,{target_blob},app/link.py",
    )
    commit = repository.index.commit("Add symbolic link entry")
    monkeypatch.setattr(git_source_reader, "PROJECT_ROOT", repo_path)

    result = get_file_content_at_commit(commit.hexsha, "app/link.py")

    assert result["status"] == "unavailable"
    assert result["content"] is None
    assert result["content_available"] is False
    assert result["error_reason"] == (
        "Symbolic links are not read as source files."
    )


def test_invalid_repository_returns_unavailable(monkeypatch):
    def raise_invalid_repository(*args, **kwargs):
        raise git.exc.InvalidGitRepositoryError("private repository path")

    monkeypatch.setattr(git_source_reader.git, "Repo", raise_invalid_repository)

    result = get_file_content_at_commit("abc123", "app/example.py")

    assert result["status"] == "unavailable"
    assert result["error_reason"] == "Git repository is unavailable."
    assert "private" not in result["error_reason"]


def test_unreadable_blob_returns_unavailable(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        {"app/example.py": "value = 1\n"},
    )

    def raise_read_error(blob):
        raise OSError("private read detail")

    monkeypatch.setattr(git_source_reader, "_read_blob_bytes", raise_read_error)
    result = _read_from_repository(
        monkeypatch,
        repo_path,
        commit_hash,
        "app/example.py",
    )

    assert result["status"] == "unavailable"
    assert result["error_reason"] == "File content could not be read."
    assert "private" not in result["error_reason"]


def test_invalid_utf8_is_reported_explicitly(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, commit_hash = _create_repository(
        repo_path,
        {"app/example.py": b"value = '\xff'\n"},
    )

    result = _read_from_repository(
        monkeypatch,
        repo_path,
        commit_hash,
        "app/example.py",
    )

    assert result["status"] == "unavailable"
    assert result["content"] is None
    assert result["content_available"] is False
    assert result["error_reason"] == "File content is not valid UTF-8."
