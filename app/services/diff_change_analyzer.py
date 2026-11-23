import re
from dataclasses import dataclass


_HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$"
)


@dataclass
class _HunkState:
    old_line: int
    new_line: int
    old_remaining: int
    new_remaining: int

    @property
    def is_complete(self) -> bool:
        return self.old_remaining == 0 and self.new_remaining == 0


def _finish_hunk(hunk: _HunkState) -> None:
    if not hunk.is_complete:
        raise ValueError("Incomplete diff hunk: line counts do not match header")


def extract_changed_lines(patch: str) -> dict:
    """Extract added and deleted source lines and their respective line numbers.

    Added line numbers refer to the new file; deleted line numbers refer to
    the old file. Malformed headers and hunks whose contents do not match their
    declared ranges raise ``ValueError`` rather than yielding unreliable data.
    """
    if not isinstance(patch, str):
        raise TypeError("patch must be a string")

    added_lines = []
    deleted_lines = []
    hunk = None

    for line in patch.splitlines():
        if line.startswith("@@"):
            if hunk is not None:
                _finish_hunk(hunk)

            match = _HUNK_HEADER.match(line)
            if match is None:
                raise ValueError(f"Malformed diff hunk header: {line}")

            old_start, old_count, new_start, new_count = match.groups()
            hunk = _HunkState(
                old_line=int(old_start),
                new_line=int(new_start),
                old_remaining=int(old_count) if old_count is not None else 1,
                new_remaining=int(new_count) if new_count is not None else 1,
            )
            continue

        if hunk is None:
            continue

        if line == r"\ No newline at end of file":
            continue

        if line.startswith(("diff --git ", "index ")):
            _finish_hunk(hunk)
            hunk = None
            continue

        if hunk.is_complete:
            if line.startswith(("--- ", "+++ ")):
                hunk = None
                continue
            if line.startswith((" ", "+", "-")):
                raise ValueError("Diff hunk contains more lines than declared")
            hunk = None

        if line.startswith("+"):
            if hunk.new_remaining == 0:
                raise ValueError("Diff hunk contains more added lines than declared")
            added_lines.append({
                "line_number": hunk.new_line,
                "content": line[1:],
            })
            hunk.new_line += 1
            hunk.new_remaining -= 1

        elif line.startswith("-"):
            if hunk.old_remaining == 0:
                raise ValueError("Diff hunk contains more deleted lines than declared")
            deleted_lines.append({
                "line_number": hunk.old_line,
                "content": line[1:],
            })
            hunk.old_line += 1
            hunk.old_remaining -= 1

        elif line.startswith(" "):
            if hunk.old_remaining == 0 or hunk.new_remaining == 0:
                raise ValueError("Diff hunk contains more context lines than declared")
            hunk.old_line += 1
            hunk.new_line += 1
            hunk.old_remaining -= 1
            hunk.new_remaining -= 1

        else:
            raise ValueError(f"Malformed diff hunk line: {line}")

    if hunk is not None:
        _finish_hunk(hunk)

    return {
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
        "summary": {
            "total_added": len(added_lines),
            "total_deleted": len(deleted_lines),
        },
    }
