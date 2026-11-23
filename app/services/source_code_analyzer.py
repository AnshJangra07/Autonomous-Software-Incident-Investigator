
import os
from collections.abc import Iterator
from pathlib import Path
import re

from app.services.ast_code_analyzer import find_containing_function

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRECTORY = PROJECT_ROOT / "app"
MAX_RESULTS = 10
MAX_ALLOWED_RESULTS = 50
MIN_RELEVANCE_SCORE = 3

STOP_WORDS = {
    "this", "that", "with", "from", "into",
    "have", "been", "were", "when", "where",
    "what", "which", "then", "than", "they",
    "them", "your", "their", "will", "would",
}


def extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text."""

    words = re.findall(r"[a-zA-Z_]{4,}", text.lower())

    return {
        word
        for word in words
        if word not in STOP_WORDS
    }


def _resolve_source_file(
    source_file: Path,
    resolved_source_directory: Path,
) -> Path | None:
    """Return a readable regular file contained by the resolved source root."""

    try:
        if source_file.is_symlink():
            return None

        resolved_source_file = source_file.resolve(strict=True)
        resolved_source_file.relative_to(resolved_source_directory)

        if not resolved_source_file.is_file():
            return None

    except (OSError, RuntimeError, ValueError):
        return None

    return resolved_source_file


def _iter_python_files(source_directory: Path) -> Iterator[Path]:
    """Walk Python files without descending into symlinked directories."""

    def ignore_walk_error(_: OSError) -> None:
        return

    for current_directory, directory_names, file_names in os.walk(
        source_directory,
        topdown=True,
        onerror=ignore_walk_error,
        followlinks=False,
    ):
        current_path = Path(current_directory)
        safe_directory_names = []

        for directory_name in directory_names:
            directory_path = current_path / directory_name
            try:
                if directory_path.is_symlink():
                    continue
            except (OSError, RuntimeError):
                continue

            safe_directory_names.append(directory_name)

        directory_names[:] = safe_directory_names

        for file_name in file_names:
            source_file = current_path / file_name
            if source_file.match("*.py"):
                yield source_file


def search_source_code(
    incident: dict,
    max_results: int = MAX_RESULTS,
) -> list[dict]:
    """
    Search application source code using weighted keyword relevance.

    Failure type and error message receive higher priority
    than endpoint information.

    Results are evidence, not confirmed root causes.
    """

    if not isinstance(incident, dict):
        raise TypeError("incident must be a dictionary")

    if not isinstance(max_results, int) or isinstance(max_results, bool):
        raise TypeError("max_results must be an integer")

    if max_results < 1:
        raise ValueError("max_results must be greater than zero")

    if max_results > MAX_ALLOWED_RESULTS:
        raise ValueError(
            f"max_results must not exceed {MAX_ALLOWED_RESULTS}"
        )

    failure_type = str(incident.get("failure_type", "")).strip()
    message = str(incident.get("message", "")).strip()
    endpoint = str(incident.get("endpoint", "")).strip()

    primary_keywords = extract_keywords(
        f"{failure_type} {message}"
    )

    endpoint_keywords = extract_keywords(endpoint)

    if not primary_keywords and not endpoint_keywords:
        return []

    try:
        resolved_source_directory = SOURCE_DIRECTORY.resolve(strict=True)
    except (OSError, RuntimeError):
        return []

    if not resolved_source_directory.is_dir():
        return []

    results = []

    for source_file in _iter_python_files(SOURCE_DIRECTORY):
        resolved_source_file = _resolve_source_file(
            source_file,
            resolved_source_directory,
        )
        if resolved_source_file is None:
            continue

        try:
            lines = resolved_source_file.read_text(
                encoding="utf-8"
            ).splitlines()

        except (OSError, UnicodeDecodeError):
            continue

        for line_number, line in enumerate(lines, start=1):

            line_lower = line.lower()

            primary_matches = sorted(
                keyword
                for keyword in primary_keywords
                if keyword in line_lower
            )

            endpoint_matches = sorted(
                keyword
                for keyword in endpoint_keywords
                if keyword in line_lower
                and keyword not in primary_keywords
            )

            if not primary_matches and not endpoint_matches:
                continue

            # Primary evidence is more valuable than endpoint matches.
            score = (
                len(primary_matches) * 3
                + len(endpoint_matches)
            )
            if score < MIN_RELEVANCE_SCORE:
                continue

            relative_file = str(source_file.relative_to(PROJECT_ROOT))

            function_info = find_containing_function(
                str(resolved_source_file),
                line_number,
            )

            results.append({
                "file": relative_file,
                "line_number": line_number,
                "matching_keywords": primary_matches + endpoint_matches,
                "relevance_score": score,
                "code_snippet": line.strip(),
                "start_line": max(1, line_number - 2),
                "end_line": min(len(lines), line_number + 2),
                "context": "\n".join(
                    lines[max(0, line_number - 3):line_number + 2]
                ),
                "function": function_info,
            })

    # Highest relevance first.
    results.sort(
        key=lambda result: (
            -result["relevance_score"],
            result["file"],
            result["line_number"],
        )
    )

    return results[:max_results]
