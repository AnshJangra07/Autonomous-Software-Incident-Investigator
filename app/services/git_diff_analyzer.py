
from pathlib import Path

import git


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_commit_diff(commit_hash: str, file_path: str) -> dict:
    """
    Retrieve the diff introduced by a commit for a specific file.

    This function is read-only.
    """

    if not isinstance(commit_hash, str) or not commit_hash.strip():
        raise ValueError("commit_hash must be a non-empty string")

    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("file_path must be a non-empty string")

    requested_path = Path(file_path)

    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    resolved_path = (PROJECT_ROOT / requested_path).resolve()

    try:
        relative_path = resolved_path.relative_to(PROJECT_ROOT)
    except ValueError:
        raise ValueError("File must be inside the project directory")

    if relative_path.parts[0] != "app" or resolved_path.suffix != ".py":
        raise ValueError("Only Python files inside app/ are allowed")

    repository = git.Repo(
        PROJECT_ROOT,
        search_parent_directories=False,
    )

    commit = repository.commit(commit_hash)

    if commit.parents:
        diffs = commit.parents[0].diff(
            commit,
            paths=relative_path.as_posix(),
            create_patch=True,
        )
    else:
        diffs = repository.tree().diff(
            commit,
            paths=relative_path.as_posix(),
            create_patch=True,
        )

    if not diffs:
        return {
            "commit_hash": commit.hexsha,
            "file": relative_path.as_posix(),
            "diff_found": False,
            "patch": "",
        }

    patches = []

    for diff in diffs:
        patch = diff.diff

        if isinstance(patch, bytes):
            patch = patch.decode("utf-8", errors="replace")

        patches.append(patch)

    return {
        "commit_hash": commit.hexsha,
        "file": relative_path.as_posix(),
        "diff_found": True,
        "patch": "\n".join(patches),
    }
