
import ast
from pathlib import Path


def extract_functions(file_path: str) -> list[dict]:
    """
    Extract function and method definitions from a Python file.

    Uses Python AST without executing the source code.
    """

    path = Path(file_path)

    if not path.exists():
        return []

    try:
        source_code = path.read_text(encoding="utf-8")
        syntax_tree = ast.parse(source_code)

    except (OSError, UnicodeDecodeError, SyntaxError):
        return []

    functions = []

    for node in ast.walk(syntax_tree):

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):

            functions.append({
                "function_name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })

    functions.sort(key=lambda item: item["start_line"])

    return functions



def find_containing_function(
    file_path: str,
    line_number: int,
) -> dict | None:
    """
    Find the function containing a specific source-code line.
    """

    if (
        isinstance(line_number, bool)
        or not isinstance(line_number, int)
        or line_number < 1
    ):
        raise ValueError("line_number must be a positive integer")

    functions = extract_functions(file_path)

    matching_functions = [
        function
        for function in functions
        if function["start_line"] <= line_number <= function["end_line"]
    ]

    if not matching_functions:
        return None

    # Select the innermost function if functions are nested.
    return min(
        matching_functions,
        key=lambda function: (
            function["end_line"] - function["start_line"]
        ),
    )
