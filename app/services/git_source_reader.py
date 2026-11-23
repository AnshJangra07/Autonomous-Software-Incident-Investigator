from pathlib import Path
import stat
from typing import Literal

import git
from git.exc import (
    BadName,
    BadObject,
    GitError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

_Status = Literal["available", "not_found", "unavailable", "invalid_input"]


def _result(
    commit_hash: str,
    file_path: str,
    content: str | None,
    status: _Status,
    error_reason: str | None = None,
) -> dict:
    result = {
        "commit_hash": commit_hash,
        "file_path": file_path,
        "content": content,
        "content_available": content is not None,
        "status": status,
    }
    if error_reason is not None:
        result["error_reason"] = error_reason
    return result


def _read_blob_bytes(blob: git.Blob) -> bytes:
    """Read blob bytes directly from Git's object database."""
    return blob.data_stream.read()


def get_file_content_at_commit(
    commit_hash: str,
    file_path: str,
) -> dict:
    """Read a Python file's UTF-8 content from a commit without checking it out."""
    safe_commit_hash = commit_hash if isinstance(commit_hash, str) else ""
    safe_file_path = (
        file_path
        if isinstance(file_path, str) and not Path(file_path).is_absolute()
        else ""
    )

    if not isinstance(commit_hash, str) or not commit_hash.strip():
        return _result(
            safe_commit_hash,
            safe_file_path,
            None,
            "invalid_input",
            "commit_hash must be a non-empty string.",
        )

    if not isinstance(file_path, str) or not file_path.strip():
        return _result(
            safe_commit_hash,
            safe_file_path,
            None,
            "invalid_input",
            "file_path must be a non-empty string.",
        )

    requested_path = Path(file_path)
    if requested_path.is_absolute():
        return _result(
            safe_commit_hash,
            "",
            None,
            "invalid_input",
            "Absolute paths are not allowed.",
        )

    try:
        project_root = Path(PROJECT_ROOT).resolve()
        resolved_path = (project_root / requested_path).resolve()
        relative_path = resolved_path.relative_to(project_root)
    except (OSError, ValueError):
        return _result(
            safe_commit_hash,
            safe_file_path,
            None,
            "invalid_input",
            "File must be inside the project app directory.",
        )

    if relative_path.suffix != ".py":
        return _result(
            safe_commit_hash,
            relative_path.as_posix(),
            None,
            "invalid_input",
            "Only Python files inside app/ are allowed.",
        )

    if not relative_path.parts or relative_path.parts[0] != "app":
        return _result(
            safe_commit_hash,
            relative_path.as_posix(),
            None,
            "invalid_input",
            "File must be inside the project app directory.",
        )

    relative_git_path = relative_path.as_posix()

    try:
        repository = git.Repo(
            project_root,
            search_parent_directories=False,
        )
    except GitError:
        return _result(
            safe_commit_hash,
            relative_git_path,
            None,
            "unavailable",
            "Git repository is unavailable.",
        )

    try:
        commit = repository.commit(commit_hash)
    except (BadName, BadObject):
        return _result(
            safe_commit_hash,
            relative_git_path,
            None,
            "not_found",
            "Commit was not found.",
        )
    except (GitError, OSError):
        return _result(
            safe_commit_hash,
            relative_git_path,
            None,
            "unavailable",
            "Commit content is unavailable.",
        )

    try:
        blob = commit.tree / relative_git_path
    except (IndexError, KeyError):
        return _result(
            commit.hexsha,
            relative_git_path,
            None,
            "not_found",
            "File was not found in the commit.",
        )
    except (BadObject, GitError, OSError):
        return _result(
            commit.hexsha,
            relative_git_path,
            None,
            "unavailable",
            "File content is unavailable.",
        )

    if not isinstance(blob, git.Blob):
        return _result(
            commit.hexsha,
            relative_git_path,
            None,
            "not_found",
            "File was not found in the commit.",
        )

    if stat.S_ISLNK(blob.mode):
        return _result(
            commit.hexsha,
            relative_git_path,
            None,
            "unavailable",
            "Symbolic links are not read as source files.",
        )

    try:
        content_bytes = _read_blob_bytes(blob)
    except (BadObject, GitError, OSError):
        return _result(
            commit.hexsha,
            relative_git_path,
            None,
            "unavailable",
            "File content could not be read.",
        )

    if not isinstance(content_bytes, bytes):
        return _result(
            commit.hexsha,
            relative_git_path,
            None,
            "unavailable",
            "File content could not be read.",
        )

    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return _result(
            commit.hexsha,
            relative_git_path,
            None,
            "unavailable",
            "File content is not valid UTF-8.",
        )

    return _result(
        commit.hexsha,
        relative_git_path,
        content,
        "available",
    )
