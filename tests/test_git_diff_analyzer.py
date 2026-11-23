
from app.services.git_diff_analyzer import get_commit_diff


def test_retrieves_real_commit_diff():
    result = get_commit_diff(
        "b3d9c04",
        "app/services/source_code_analyzer.py",
    )

    assert result["diff_found"] is True
    assert result["file"] == "app/services/source_code_analyzer.py"
    assert result["commit_hash"].startswith("b3d9c04")

    assert "find_containing_function" in result["patch"]
    assert '"function": function_info' in result["patch"]



import pytest


def test_empty_commit_hash_is_rejected():
    with pytest.raises(ValueError, match="commit_hash"):
        get_commit_diff("", "app/api/routes.py")


def test_empty_file_path_is_rejected():
    with pytest.raises(ValueError, match="file_path"):
        get_commit_diff("b3d9c04", "")


def test_absolute_file_path_is_rejected():
    with pytest.raises(ValueError, match="Absolute paths"):
        get_commit_diff(
            "b3d9c04",
            r"C:\Users\example\app\api\routes.py",
        )


def test_file_outside_app_is_rejected():
    with pytest.raises(ValueError, match="Only Python files"):
        get_commit_diff("b3d9c04", "tests/test_api.py")



def test_path_traversal_is_rejected():
    with pytest.raises(ValueError, match="inside the project"):
        get_commit_diff(
            "b3d9c04",
            "app/../../outside.py",
        )


def test_non_python_file_is_rejected():
    with pytest.raises(ValueError, match="Only Python files"):
        get_commit_diff(
            "b3d9c04",
            "app/services/config.json",
        )