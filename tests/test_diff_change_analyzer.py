import pytest

from app.services.diff_change_analyzer import extract_changed_lines


def test_extracts_added_lines_using_new_file_numbers():
    patch = "@@ -10,1 +10,2 @@\n context\n+new_code = True\n"

    assert extract_changed_lines(patch) == {
        "added_lines": [
            {"line_number": 11, "content": "new_code = True"},
        ],
        "deleted_lines": [],
        "summary": {"total_added": 1, "total_deleted": 0},
    }


def test_extracts_deleted_lines_using_old_file_numbers():
    patch = "@@ -14,1 +13,0 @@\n-old_code = False\n"

    result = extract_changed_lines(patch)

    assert result["deleted_lines"] == [
        {"line_number": 14, "content": "old_code = False"},
    ]
    assert result["summary"] == {"total_added": 0, "total_deleted": 1}


def test_represents_modification_as_deletion_and_addition():
    patch = "@@ -14 +14 @@\n-old_code = False\n+new_code = True\n"

    result = extract_changed_lines(patch)

    assert result["deleted_lines"] == [
        {"line_number": 14, "content": "old_code = False"},
    ]
    assert result["added_lines"] == [
        {"line_number": 14, "content": "new_code = True"},
    ]


def test_extracts_lines_from_multiple_hunks():
    patch = (
        "@@ -2,1 +2,1 @@\n-old_first\n+new_first\n"
        "@@ -20,1 +20,1 @@\n-old_second\n+new_second\n"
    )

    result = extract_changed_lines(patch)

    assert [line["line_number"] for line in result["added_lines"]] == [2, 20]
    assert [line["line_number"] for line in result["deleted_lines"]] == [2, 20]


def test_context_lines_advance_both_line_counters():
    patch = "@@ -5,3 +8,3 @@\n first\n-old\n+new\n last\n"

    result = extract_changed_lines(patch)

    assert result["deleted_lines"] == [{"line_number": 6, "content": "old"}]
    assert result["added_lines"] == [{"line_number": 9, "content": "new"}]


def test_empty_patch_returns_empty_result():
    assert extract_changed_lines("") == {
        "added_lines": [],
        "deleted_lines": [],
        "summary": {"total_added": 0, "total_deleted": 0},
    }


def test_diff_without_changes_returns_empty_lists():
    patch = (
        "diff --git a/example.py b/example.py\n"
        "index 1234567..abcdefg 100644\n"
        "--- a/example.py\n"
        "+++ b/example.py\n"
    )

    result = extract_changed_lines(patch)

    assert result["added_lines"] == []
    assert result["deleted_lines"] == []
    assert result["summary"] == {"total_added": 0, "total_deleted": 0}


def test_ignores_no_newline_metadata():
    patch = "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n"

    result = extract_changed_lines(patch)

    assert result["deleted_lines"] == [{"line_number": 1, "content": "old"}]
    assert result["added_lines"] == [{"line_number": 1, "content": "new"}]


def test_file_headers_are_not_treated_as_code_changes():
    patch = (
        "diff --git a/example.py b/example.py\n"
        "--- a/example.py\n"
        "+++ b/example.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    result = extract_changed_lines(patch)

    assert result["added_lines"] == [{"line_number": 1, "content": "new"}]
    assert result["deleted_lines"] == [{"line_number": 1, "content": "old"}]


def test_rejects_non_string_input():
    with pytest.raises(TypeError, match="patch must be a string"):
        extract_changed_lines(None)


@pytest.mark.parametrize(
    "patch",
    [
        "@@ malformed @@\n+new\n",
        "@@ -1,2 +1,1 @@\n-old\n",
        "@@ -1 +1 @@\n-old\n+new\n+extra\n",
    ],
)
def test_rejects_malformed_or_incomplete_hunks(patch):
    with pytest.raises(ValueError):
        extract_changed_lines(patch)
