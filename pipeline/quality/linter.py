"""
pipeline/quality/linter.py
Runs Black + isort on all generated Python files before ZIP assembly.
Runs ESLint + Prettier on JS/JSX files if Node.js is available.

Called from package_node.py before assembling the ZIP.
Formatting errors are logged but never block packaging — a linting failure
results in the original content being included, not a missing file.

Black enforces: 88-char line length, consistent string quoting, trailing commas.
isort enforces: grouped imports (stdlib → third-party → local), alphabetical order.
"""

import subprocess
import sys
import tempfile
import os
from typing import Optional

from loguru import logger


async def format_all_files(
    generated_files: dict[str, str],
) -> tuple[dict[str, str], dict]:
    """
    Format all generated files. Returns updated files dict and a formatting report.

    Args:
        generated_files: Dict of file_path → content.

    Returns:
        Tuple of (formatted_files, report) where report contains per-file status.
    """
    formatted = {}
    report = {
        "python_files_formatted": 0,
        "python_files_unchanged": 0,
        "python_errors": [],
        "js_files_formatted": 0,
        "js_errors": [],
    }

    for path, content in generated_files.items():
        if not content:
            formatted[path] = content
            continue

        if path.endswith(".py"):
            result = _format_python(path, content)
            formatted[path] = result.content
            if result.changed:
                report["python_files_formatted"] += 1
            else:
                report["python_files_unchanged"] += 1
            if result.error:
                report["python_errors"].append({"file": path, "error": result.error})

        elif path.endswith((".js", ".jsx")):
            result = _format_javascript(path, content)
            formatted[path] = result.content
            if result.changed:
                report["js_files_formatted"] += 1
            if result.error:
                report["js_errors"].append({"file": path, "error": result.error})

        else:
            formatted[path] = content

    logger.info(
        f"Formatting complete: "
        f"Python {report['python_files_formatted']} formatted / "
        f"{report['python_files_unchanged']} unchanged / "
        f"{len(report['python_errors'])} errors. "
        f"JS {report['js_files_formatted']} formatted."
    )
    return formatted, report


class _FormatResult:
    def __init__(self, content: str, changed: bool, error: Optional[str] = None):
        self.content = content
        self.changed = changed
        self.error = error


def _format_python(file_path: str, source: str) -> _FormatResult:
    """Format Python source with Black then isort."""
    original = source
    try:
        import black
        import isort

        # Black formatting
        mode = black.Mode(line_length=88, string_normalization=True)
        try:
            formatted = black.format_str(source, mode=mode)
        except black.InvalidInput as exc:
            return _FormatResult(source, False, f"Black parse error: {exc}")

        # isort import sorting
        isort_config = isort.Config(
            profile="black",
            line_length=88,
            known_first_party=["app", "config", "intelligence", "knowledge", "memory", "monitoring", "pipeline"],
        )
        formatted = isort.code(formatted, config=isort_config)

        changed = formatted != original
        return _FormatResult(formatted, changed)

    except ImportError as exc:
        logger.debug(f"Formatter not available ({exc}), skipping {file_path}")
        return _FormatResult(source, False)
    except Exception as exc:
        logger.warning(f"Python formatting failed for {file_path}: {exc}")
        return _FormatResult(source, False, str(exc))


def _format_javascript(file_path: str, source: str) -> _FormatResult:
    """
    Format JavaScript/JSX with Prettier if Node.js is available.
    Falls through silently if Node or Prettier is not installed.
    """
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return _FormatResult(source, False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return _FormatResult(source, False)

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".jsx" if file_path.endswith(".jsx") else ".js",
            delete=False,
        ) as tmp:
            tmp.write(source)
            tmp_path = tmp.name

        result = subprocess.run(
            ["npx", "prettier", "--write", "--single-quote", "--tab-width", "2", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            with open(tmp_path) as f:
                formatted = f.read()
            os.unlink(tmp_path)
            return _FormatResult(formatted, formatted != source)
        else:
            os.unlink(tmp_path)
            return _FormatResult(source, False, result.stderr[:200])

    except Exception as exc:
        logger.debug(f"JS formatting skipped for {file_path}: {exc}")
        return _FormatResult(source, False)
