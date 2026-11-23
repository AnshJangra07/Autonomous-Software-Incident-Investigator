
from pathlib import Path

import git
from git.exc import GitCommandError, InvalidGitRepositoryError


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MAX_COMMITS = 10
MAX_ALLOWED_COMMITS = 50


def get_file_commit_history(
    file_path: str,
    max_commits: int = MAX_COMMITS,
) -> list[dict]:
    """
    Retrieve recent Git commits affecting a project source file.

    This function is read-only. It does not modify the repository.
    """

    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("file_path must be a non-empty string")

    if not isinstance(max_commits, int) or isinstance(max_commits, bool):
        raise TypeError("max_commits must be an integer")

    if max_commits < 1:
        raise ValueError("max_commits must be greater than zero")

    if max_commits > MAX_ALLOWED_COMMITS:
        raise ValueError(
            f"max_commits must not exceed {MAX_ALLOWED_COMMITS}"
        )

    # Resolve and validate the requested path.
    requested_path = Path(file_path)

    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    resolved_path = (PROJECT_ROOT / requested_path).resolve()

    # Prevent path traversal outside the project.
    try:
        relative_path = resolved_path.relative_to(PROJECT_ROOT)
    except ValueError:
        raise ValueError("File must be inside the project directory")

    # Only inspect Python application source files.
    if (
        relative_path.parts[0] != "app"
        or resolved_path.suffix != ".py"
        or not resolved_path.is_file()
    ):
        raise ValueError("Only existing Python files inside app/ are allowed")

    try:
        repository = git.Repo(
            PROJECT_ROOT,
            search_parent_directories=False,
        )

        if repository.bare:
            return []

        relative_git_path = relative_path.as_posix()

        commits = repository.iter_commits(
            paths=relative_git_path,
            max_count=max_commits,
        )

        history = []

        for commit in commits:
            history.append({
                "commit_hash": commit.hexsha,
                "short_hash": commit.hexsha[:8],
                "author": str(commit.author),
                "date": commit.committed_datetime.isoformat(),
                "message": commit.message.strip(),
                "changed_files": list(commit.stats.files.keys()),
            })

        return history

    except (InvalidGitRepositoryError, GitCommandError):
        return []

