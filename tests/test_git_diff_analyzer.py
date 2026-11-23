
import git
import pytest
from git.exc import (
    BadName,
    GitCommandError,
    InvalidGitRepositoryError,
)

from app.services import git_diff_analyzer
from app.services.git_diff_analyzer import get_commit_diff


def _create_repository(repo_path):
    repo_path.mkdir()
    repository = git.Repo.init(repo_path)

    with repository.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")

    source_file = repo_path / "app" / "sample.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("value = 1\n", encoding="utf-8")
    repository.index.add(["app/sample.py"])
    first_commit = repository.index.commit("Add sample source")
    return repository, first_commit


def test_retrieves_real_commit_diff():
    result = get_commit_diff(
        "b3d9c04",
        "app/services/source_code_analyzer.py",
    )

    assert result["diff_found"] is True
    assert result["file"] == "app/services/source_code_analyzer.py"
    assert result["commit_hash"].startswith("b3d9c04")

    assert "find_containing_function" in result["patch"]
    assert '"function": function_info' in result["patch"]


def test_successfully_retrieved_empty_diff_is_no_diff(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    repository, _ = _create_repository(repo_path)
    unrelated_file = repo_path / "app" / "unrelated.py"
    unrelated_file.write_text("unrelated = True\n", encoding="utf-8")
    repository.index.add(["app/unrelated.py"])
    commit = repository.index.commit("Add unrelated source")
    monkeypatch.setattr(git_diff_analyzer, "PROJECT_ROOT", repo_path)

    result = get_commit_diff(commit.hexsha, "app/sample.py")

    assert result["diff_found"] is False
    assert result["patch"] == ""


def test_invalid_git_repository_raises_instead_of_returning_no_diff(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(git_diff_analyzer, "PROJECT_ROOT", tmp_path)

    with pytest.raises(InvalidGitRepositoryError):
        get_commit_diff("abc123", "app/sample.py")


def test_git_command_failure_propagates(tmp_path, monkeypatch):
    class FailingParent:
        def diff(self, *args, **kwargs):
            raise GitCommandError("git diff", 1)

    class FakeCommit:
        hexsha = "a" * 40
        parents = [FailingParent()]

    class FakeRepository:
        def commit(self, commit_hash):
            return FakeCommit()

    monkeypatch.setattr(git_diff_analyzer, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        git_diff_analyzer.git,
        "Repo",
        lambda *args, **kwargs: FakeRepository(),
    )

    with pytest.raises(GitCommandError):
        get_commit_diff("abc123", "app/sample.py")


def test_invalid_commit_propagates_as_git_error(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _create_repository(repo_path)
    monkeypatch.setattr(git_diff_analyzer, "PROJECT_ROOT", repo_path)

    with pytest.raises(BadName):
        get_commit_diff("not-a-commit", "app/sample.py")



def test_empty_commit_hash_is_rejected():
    with pytest.raises(ValueError, match="commit_hash"):
        get_commit_diff("", "app/api/routes.py")


def test_empty_file_path_is_rejected():
    with pytest.raises(ValueError, match="file_path"):
        get_commit_diff("b3d9c04", "")


def test_absolute_file_path_is_rejected():
    with pytest.raises(ValueError, match="Absolute paths"):
        get_commit_diff(
            "b3d9c04",
            r"C:\Users\example\app\api\routes.py",
        )


def test_file_outside_app_is_rejected():
    with pytest.raises(ValueError, match="Only Python files"):
        get_commit_diff("b3d9c04", "tests/test_api.py")



def test_path_traversal_is_rejected():
    with pytest.raises(ValueError, match="inside the project"):
        get_commit_diff(
            "b3d9c04",
            "app/../../outside.py",
        )


def test_non_python_file_is_rejected():
    with pytest.raises(ValueError, match="Only Python files"):
        get_commit_diff(
            "b3d9c04",
            "app/services/config.json",
        )