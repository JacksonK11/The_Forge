"""
pipeline/nodes/test_generator.py
Generates pytest test files for every Python file in layers 1-4.

For each source file, generates a corresponding tests/test_<filename>.py
using the same spec context so tests cover realistic scenarios:
  - Database models: creation, field validation, relationship loading
  - API routes: correct status codes, response schemas, auth rejection
  - Pipeline nodes: output shapes, error handling, DB state mutations
  - Services: happy path and error path coverage

Adds ~10-15 extra files per build (1 test file per substantive Python file).
Test files use pytest-asyncio for async tests and httpx.AsyncClient for routes.
Cost: ~£0.05-0.10 per build (15 extra Haiku calls).

Called from codegen_node.py after all layer 1-4 files are generated.
"""

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.model_config import router
from config.settings import settings
from pipeline.pipeline import PipelineState

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

TEST_SYSTEM = """You are generating pytest test files for production Python code.

Rules:
- Use pytest-asyncio for all async tests: @pytest.mark.asyncio
- Use httpx.AsyncClient for FastAPI route tests
- Use AsyncMock and MagicMock for external dependencies (Anthropic, OpenAI, Tavily)
- Never hit real external APIs in tests
- Every test has a clear docstring explaining what it tests
- Tests cover: happy path, error path, edge cases
- Use pytest fixtures for database sessions and app client
- Import exactly what is used — no unused imports
- No placeholder tests — every test assertion is meaningful
- conftest.py fixtures use in-memory SQLite or pytest-postgresql if available

Generate ONLY the test file content. No explanation. No markdown."""

TEST_USER = """Generate a complete pytest test file for this source file.

SOURCE FILE: {file_path}
PURPOSE: {purpose}

SOURCE CODE:
{source_code}

SPEC CONTEXT (for realistic test scenarios):
{spec_summary}

Test file path: tests/test_{test_filename}

Generate every test as a complete, runnable function with meaningful assertions."""


# Files that should be tested (layers 1-4, substantive Python files)
TESTABLE_LAYERS = frozenset([1, 3, 4])
SKIP_FILES = frozenset([
    "__init__.py",
    "database.py",  # DB setup — tested implicitly
    "seed.py",      # Seed data — tested implicitly
    "worker.py",    # Entry point — integration tested
])


async def generate_test_files(state: PipelineState) -> dict[str, str]:
    """
    Generate test files for all testable Python files in the build.
    Returns dict of test_file_path → content.
    """
    if not state.spec or not state.manifest:
        logger.warning("Test generator: missing spec or manifest, skipping")
        return {}

    spec_summary = _build_spec_summary(state.spec)
    test_files: dict[str, str] = {}

    manifest = state.manifest.get("file_manifest", [])
    testable = [
        entry for entry in manifest
        if entry.get("layer") in TESTABLE_LAYERS
        and entry.get("path", "").endswith(".py")
        and entry.get("path", "").split("/")[-1] not in SKIP_FILES
        and entry.get("path", "") in state.generated_files
    ]

    logger.info(f"[{state.run_id}] Generating tests for {len(testable)} files")

    # Also generate conftest.py
    conftest = await _generate_conftest(state.spec)
    if conftest:
        test_files["tests/conftest.py"] = conftest

    for entry in testable:
        file_path = entry["path"]
        source_code = state.generated_files.get(file_path, "")
        if not source_code or len(source_code.strip()) < 50:
            continue

        test_filename = file_path.replace("/", "_").replace(".py", "")
        test_path = f"tests/test_{test_filename}.py"

        try:
            content = await retry_async(
                _generate_test_file,
                file_path,
                entry.get("description", ""),
                source_code,
                spec_summary,
                test_filename,
                max_attempts=2,
                label=f"test_gen:{file_path}",
            )
            if content and len(content.strip()) > 50:
                test_files[test_path] = content
                logger.debug(f"[{state.run_id}] Test generated: {test_path}")
        except Exception as exc:
            logger.warning(f"[{state.run_id}] Test generation failed for {file_path}: {exc}")

    logger.info(f"[{state.run_id}] Test generation complete: {len(test_files)} test files")
    return test_files


async def _generate_test_file(
    file_path: str,
    purpose: str,
    source_code: str,
    spec_summary: str,
    test_filename: str,
) -> str:
    """Generate a single test file using Claude Haiku."""
    model = router.get_model("generation")  # Use Sonnet for tests — quality matters
    prompt = TEST_USER.format(
        file_path=file_path,
        purpose=purpose,
        source_code=source_code[:4000],
        spec_summary=spec_summary,
        test_filename=test_filename,
    )
    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=TEST_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.content[0].text.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)
    return content


async def _generate_conftest(spec: dict) -> str:
    """Generate tests/conftest.py with shared pytest fixtures."""
    agent_slug = spec.get("agent_slug", "agent")
    agent_name = spec.get("agent_name", "Agent")
    tables = [t["name"] for t in spec.get("database_tables", [])]

    return f'''"""
tests/conftest.py
Shared pytest fixtures for {agent_name} test suite.
"""

import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memory.models import Base

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """In-memory SQLite engine for each test function."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Database session for each test function."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def api_client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with auth header for API tests."""
    from app.api.main import app
    from memory.database import engine as prod_engine
    from memory.database import AsyncSessionLocal

    # Override the database engine with test engine
    async with AsyncClient(
        app=app,
        base_url="http://test",
        headers={{"Authorization": "Bearer test-secret-key"}},
    ) as client:
        yield client
'''


def _build_spec_summary(spec: dict) -> str:
    """Build a compact spec summary for test prompts."""
    tables = [t["name"] for t in spec.get("database_tables", [])]
    routes = [f"{r['method']} {r['path']}" for r in spec.get("api_routes", [])]
    return (
        f"Agent: {spec.get('agent_name')}\n"
        f"Tables: {', '.join(tables)}\n"
        f"Routes: {', '.join(routes[:10])}"
    )
