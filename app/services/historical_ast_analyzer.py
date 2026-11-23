from typing import Literal

from app.services.ast_code_analyzer import extract_functions_from_source
from app.services.git_source_reader import get_file_content_at_commit


_Status = Literal[
    "available",
    "not_found",
    "unavailable",
    "invalid_input",
    "invalid_source",
]


def _result(
    commit_hash: str,
    file_path: str,
    functions: list[dict],
    status: _Status,
    error_reason: str | None = None,
) -> dict:
    result = {
        "commit_hash": commit_hash,
        "file_path": file_path,
        "functions": functions,
        "status": status,
    }
    if error_reason is not None:
        result["error_reason"] = error_reason
    return result


def analyze_historical_functions(
    commit_hash: str,
    file_path: str,
) -> dict:
    """Extract function boundaries from a Python file in a Git commit."""
    source_result = get_file_content_at_commit(commit_hash, file_path)
    if not isinstance(source_result, dict):
        return _result(
            commit_hash if isinstance(commit_hash, str) else "",
            file_path if isinstance(file_path, str) else "",
            [],
            "unavailable",
            "Historical source result is unavailable.",
        )

    result_commit_hash = source_result.get("commit_hash", commit_hash)
    if not isinstance(result_commit_hash, str):
        result_commit_hash = ""

    result_file_path = source_result.get("file_path", file_path)
    if not isinstance(result_file_path, str):
        result_file_path = ""

    source_status = source_result.get("status")
    if source_status != "available":
        if source_status not in {
            "not_found",
            "unavailable",
            "invalid_input",
        }:
            source_status = "unavailable"

        error_reason = source_result.get("error_reason")
        if not isinstance(error_reason, str) or not error_reason:
            error_reason = "Historical source is unavailable."

        return _result(
            result_commit_hash,
            result_file_path,
            [],
            source_status,
            error_reason,
        )

    source_code = source_result.get("content")
    if not isinstance(source_code, str):
        return _result(
            result_commit_hash,
            result_file_path,
            [],
            "unavailable",
            "Historical source content is unavailable.",
        )

    try:
        functions = extract_functions_from_source(source_code)
    except SyntaxError:
        return _result(
            result_commit_hash,
            result_file_path,
            [],
            "invalid_source",
            "Historical source has invalid Python syntax.",
        )

    return _result(
        result_commit_hash,
        result_file_path,
        functions,
        "available",
    )
