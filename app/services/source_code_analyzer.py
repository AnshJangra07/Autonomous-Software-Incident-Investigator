
from pathlib import Path


# Locate the project root dynamically
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Only investigate our application source code
SOURCE_DIRECTORY = PROJECT_ROOT / "app"

# Maximum number of source matches returned per investigation
MAX_RESULTS = 10


def search_source_code(
    incident: dict,
    max_results: int = MAX_RESULTS,
) -> list[dict]:
    """
    Search application source files for keywords related to an incident.

    Returns matching file paths, line numbers, snippets and keywords.
    This retrieves evidence; it does not establish root cause.
    """

    if not isinstance(incident, dict):
        raise TypeError("incident must be a dictionary")

    if max_results < 1:
        raise ValueError("max_results must be greater than zero")

    failure_type = str(incident.get("failure_type", "")).strip()
    message = str(incident.get("message", "")).strip()
    endpoint = str(incident.get("endpoint", "")).strip()

    search_text = f"{failure_type} {message} {endpoint}".lower()

    if not search_text.strip():
        return []

    keywords = {
        word.strip(".,:;()[]{}'\"!?/")
        for word in search_text.split()
        if len(word.strip(".,:;()[]{}'\"!?/")) >= 4
    }

    results = []

    if not SOURCE_DIRECTORY.exists():
        return []

    for source_file in SOURCE_DIRECTORY.rglob("*.py"):

        try:
            lines = source_file.read_text(
                encoding="utf-8"
            ).splitlines()

        except (OSError, UnicodeDecodeError):
            continue

        for line_number, line in enumerate(lines, start=1):

            line_lower = line.lower()

            matching_keywords = [
                keyword
                for keyword in sorted(keywords)
                if keyword in line_lower
            ]

            if not matching_keywords:
                continue

            results.append({
                "file": str(source_file.relative_to(PROJECT_ROOT)),
                "line_number": line_number,
                "matching_keywords": matching_keywords,
                "code_snippet": line.strip(),
            })

            if len(results) >= max_results:
                return results

    return results
