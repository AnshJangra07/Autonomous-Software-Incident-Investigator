
from app.services.ast_code_analyzer import extract_functions


def test_extracts_function_details(tmp_path):
    source_file = tmp_path / "sample.py"

    source_file.write_text(
        "def connect_database():\n"
        "    return True\n",
        encoding="utf-8",
    )

    result = extract_functions(str(source_file))

    assert len(result) == 1
    assert result[0]["function_name"] == "connect_database"
    assert result[0]["start_line"] == 1
    assert result[0]["end_line"] == 2
    assert result[0]["is_async"] is False


def test_extracts_async_functions(tmp_path):
    source_file = tmp_path / "sample.py"

    source_file.write_text(
        "async def fetch_data():\n"
        "    return True\n",
        encoding="utf-8",
    )

    result = extract_functions(str(source_file))

    assert result[0]["function_name"] == "fetch_data"
    assert result[0]["is_async"] is True


def test_extracts_class_methods(tmp_path):
    source_file = tmp_path / "sample.py"

    source_file.write_text(
        "class Database:\n"
        "    def connect(self):\n"
        "        return True\n",
        encoding="utf-8",
    )

    result = extract_functions(str(source_file))

    assert len(result) == 1
    assert result[0]["function_name"] == "connect"


def test_missing_file_returns_empty_list(tmp_path):
    result = extract_functions(
        str(tmp_path / "missing.py")
    )

    assert result == []


def test_invalid_python_file_returns_empty_list(tmp_path):
    source_file = tmp_path / "invalid.py"

    source_file.write_text(
        "def broken_function(:\n",
        encoding="utf-8",
    )

    result = extract_functions(str(source_file))

    assert result == []


def test_extracts_nested_functions(tmp_path):
    source_file = tmp_path / "sample.py"

    source_file.write_text(
        "def outer_function():\n"
        "    def inner_function():\n"
        "        return True\n"
        "    return inner_function()\n",
        encoding="utf-8",
    )

    result = extract_functions(str(source_file))

    names = [item["function_name"] for item in result]

    assert names == ["outer_function", "inner_function"]



import pytest

from app.services.ast_code_analyzer import find_containing_function


def test_finds_containing_function(tmp_path):
    source_file = tmp_path / "sample.py"

    source_file.write_text(
        "def connect_database():\n"
        "    connection = True\n"
        "    return connection\n",
        encoding="utf-8",
    )

    result = find_containing_function(str(source_file), 2)

    assert result["function_name"] == "connect_database"
    assert result["start_line"] == 1
    assert result["end_line"] == 3


def test_returns_none_for_line_outside_function(tmp_path):
    source_file = tmp_path / "sample.py"

    source_file.write_text(
        "import os\n"
        "\n"
        "def connect_database():\n"
        "    return True\n",
        encoding="utf-8",
    )

    result = find_containing_function(str(source_file), 1)

    assert result is None


def test_finds_innermost_nested_function(tmp_path):
    source_file = tmp_path / "sample.py"

    source_file.write_text(
        "def outer_function():\n"
        "    def inner_function():\n"
        "        return True\n"
        "    return inner_function()\n",
        encoding="utf-8",
    )

    result = find_containing_function(str(source_file), 3)

    assert result["function_name"] == "inner_function"


def test_rejects_invalid_line_number():
    with pytest.raises(ValueError):
        find_containing_function("sample.py", 0)


def test_rejects_boolean_line_number():
    with pytest.raises(ValueError):
        find_containing_function("sample.py", True)
