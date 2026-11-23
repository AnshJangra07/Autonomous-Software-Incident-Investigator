
import pytest

from app.services.git_history_analyzer import get_file_commit_history


def test_routes_file_returns_commit_history():
    history = get_file_commit_history("app/api/routes.py")

    assert isinstance(history, list)
    assert len(history) > 0

    first_commit = history[0]

    assert "commit_hash" in first_commit
    assert "short_hash" in first_commit
    assert "author" in first_commit
    assert "date" in first_commit
    assert "message" in first_commit
    assert "changed_files" in first_commit


def test_commit_history_respects_limit():
    history = get_file_commit_history(
        "app/api/routes.py",
        max_commits=1,
    )

    assert len(history) <= 1


def test_empty_file_path_is_rejected():
    with pytest.raises(ValueError):
        get_file_commit_history("")


def test_absolute_path_is_rejected():
    with pytest.raises(ValueError):
        get_file_commit_history(
            str(__import__("pathlib").Path(__file__).resolve())
        )


def test_files_outside_app_are_rejected():
    with pytest.raises(ValueError):
        get_file_commit_history("README.md")


def test_nonexistent_file_is_rejected():
    with pytest.raises(ValueError):
        get_file_commit_history("app/missing.py")


def test_zero_commit_limit_is_rejected():
    with pytest.raises(ValueError):
        get_file_commit_history(
            "app/api/routes.py",
            max_commits=0,
        )
