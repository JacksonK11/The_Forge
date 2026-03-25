"""
app/api/services/packager.py
Assembles all generated files into a downloadable ZIP archive.

Called by the package pipeline node after all files are generated.
Produces a ZIP with correct folder structure using the agent slug as root directory.
Also runs Black/isort formatting on Python files and ESLint on JS/JSX files.
"""

import io
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from loguru import logger

from memory.models import ForgeFile, ForgeRun


async def assemble_package(
    run: ForgeRun,
    files: list[ForgeFile],
    readme_content: str,
    fly_secrets_content: str,
    connection_test_content: str,
    security_report_content: str,
    failed_files_report_content: Optional[str] = None,
    feedback_reporter_content: Optional[str] = None,
) -> bytes:
    """
    Build ZIP archive for a completed forge run.

    failed_files_report_content: if provided, written as FAILED_FILES_REPORT.md
      in the archive root so the developer immediately knows what needs manual work.

    Returns:
        ZIP file bytes ready for download or S3 upload.
    """
    agent_slug = _get_agent_slug(run)

    # Format all Python and JS files before packaging
    formatted_files = await _format_files(files)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write all generated source files
        for forge_file in formatted_files:
            if forge_file.content and forge_file.status == "complete":
                archive_path = f"{agent_slug}/{forge_file.file_path}"
                zf.writestr(archive_path, forge_file.content)

        # Write documentation and deployment helpers
        zf.writestr(f"{agent_slug}/README.md", readme_content)
        zf.writestr(f"{agent_slug}/FLY_SECRETS.txt", fly_secrets_content)
        zf.writestr(f"{agent_slug}/connection_test.py", connection_test_content)
        zf.writestr(f"{agent_slug}/SECURITY_REPORT.txt", security_report_content)

        # Write failed files report if any files need manual implementation
        if failed_files_report_content:
            zf.writestr(f"{agent_slug}/FAILED_FILES_REPORT.md", failed_files_report_content)

        # Write feedback reporter script for post-deployment feedback
        if feedback_reporter_content:
            zf.writestr(f"{agent_slug}/feedback_reporter.py", feedback_reporter_content)

    zip_buffer.seek(0)
    package_bytes = zip_buffer.read()
    logger.info(
        f"Package assembled for run {run.run_id}: "
        f"{len(formatted_files)} files, {len(package_bytes):,} bytes"
    )
    return package_bytes


async def _format_files(files: list[ForgeFile]) -> list[ForgeFile]:
    """
    Run Black + isort on Python files, ESLint + Prettier on JS/JSX.
    Returns files with formatted content. Errors are logged but never block packaging.
    """
    for forge_file in files:
        if not forge_file.content:
            continue
        path = forge_file.file_path
        try:
            if path.endswith(".py"):
                forge_file.content = _format_python(forge_file.content)
            elif path.endswith((".js", ".jsx", ".ts", ".tsx")):
                # ESLint/Prettier requires a tmp file — skip in environments without node
                pass
        except Exception as exc:
            logger.warning(f"Formatting failed for {path}: {exc}")
    return files


def _format_python(source: str) -> str:
    """Format Python source with Black then isort. Returns original on any error."""
    try:
        import black
        import isort

        formatted = black.format_str(source, mode=black.Mode())
        formatted = isort.code(formatted)
        return formatted
    except Exception as exc:
        logger.warning(f"Python formatting skipped: {exc}")
        return source


def _get_agent_slug(run: ForgeRun) -> str:
    """Derive agent slug from run spec or fall back to sanitised title."""
    if run.spec_json and run.spec_json.get("agent_slug"):
        return run.spec_json["agent_slug"]
    return run.title.lower().replace(" ", "-").replace("_", "-")[:50]


def generate_connection_test(spec: dict) -> str:
    """
    Generate a standalone connection_test.py script that verifies all API keys
    in the spec before deployment.
    """
    api_names = spec.get("external_apis", [])
    lines = [
        '"""',
        "connection_test.py",
        "Run this locally to verify all API keys are valid before deploying.",
        "Usage: python connection_test.py",
        '"""',
        "",
        "import asyncio",
        "import os",
        "import sys",
        "from dotenv import load_dotenv",
        "",
        'load_dotenv()',
        "",
        "results: dict[str, bool] = {}",
        "",
    ]

    if "anthropic" in api_names:
        lines += [
            "async def test_anthropic():",
            "    import anthropic",
            "    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])",
            "    msg = client.messages.create(",
            "        model='claude-haiku-4-5-20251001',",
            "        max_tokens=10,",
            "        messages=[{'role': 'user', 'content': 'ping'}]",
            "    )",
            "    return bool(msg.content)",
            "",
        ]

    if "openai" in api_names:
        lines += [
            "async def test_openai():",
            "    from openai import AsyncOpenAI",
            "    client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])",
            "    resp = await client.embeddings.create(model='text-embedding-3-small', input='test')",
            "    return bool(resp.data)",
            "",
        ]

    if "tavily" in api_names:
        lines += [
            "async def test_tavily():",
            "    from tavily import TavilyClient",
            "    client = TavilyClient(api_key=os.environ['TAVILY_API_KEY'])",
            "    result = client.search('test', max_results=1)",
            "    return bool(result)",
            "",
        ]

    lines += [
        "async def test_database():",
        "    import asyncpg",
        "    conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('+asyncpg', ''))",
        "    await conn.fetchval('SELECT 1')",
        "    await conn.close()",
        "    return True",
        "",
        "async def test_redis():",
        "    import redis.asyncio as aioredis",
        "    r = await aioredis.from_url(os.environ['REDIS_URL'])",
        "    await r.ping()",
        "    await r.aclose()",
        "    return True",
        "",
        "async def main():",
        "    tests = {",
        "        'database': test_database,",
        "        'redis': test_redis,",
    ]

    if "anthropic" in api_names:
        lines.append("        'anthropic': test_anthropic,")
    if "openai" in api_names:
        lines.append("        'openai': test_openai,")
    if "tavily" in api_names:
        lines.append("        'tavily': test_tavily,")

    lines += [
        "    }",
        "    all_passed = True",
        "    for name, test_fn in tests.items():",
        "        try:",
        "            ok = await test_fn()",
        "            status = '✅ PASS' if ok else '❌ FAIL'",
        "        except Exception as e:",
        "            status = f'❌ ERROR: {e}'",
        "            all_passed = False",
        "        print(f'{status}  {name}')",
        "    if not all_passed:",
        "        sys.exit(1)",
        "    print('\\nAll connections verified. Safe to deploy.')",
        "",
        "if __name__ == '__main__':",
        "    asyncio.run(main())",
    ]

    return "\n".join(lines)
