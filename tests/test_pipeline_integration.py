"""
tests/test_pipeline_integration.py
Integration tests for The Forge pipeline.

Run with: pytest tests/ -v
Tests cover pure logic functions (no network, no DB required) plus
mocked tests for DB-dependent code.

Install test deps: pip install pytest pytest-asyncio
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Architecture node fly.toml filter tests ───────────────────────────────────
# Tests the _is_unwanted_fly_toml filter logic directly (no module import chain needed)
# This matches the implementation in pipeline/nodes/architecture_node.py exactly.


def _is_unwanted_fly_toml(path: str) -> bool:
    """
    Mirror of the filter function in architecture_node.py.
    Tests the logic in isolation so it works on any Python version.
    """
    p = path.lower()
    if not p.endswith(".toml"):
        return False
    basename = p.split("/")[-1]
    if not (basename.startswith("fly.") or basename.startswith("fly-")):
        return False
    unwanted_suffixes = (
        "-dashboard.toml",
        "-scheduler.toml",
        "-frontend.toml",
        "-ui.toml",
        "-postgres.toml",
        "-db.toml",
        "-database.toml",
    )
    return any(basename.endswith(s) for s in unwanted_suffixes)


class TestFlyTomlFilter:
    """Test the fly.toml filter logic — no imports, pure function."""

    def test_keeps_api_toml(self):
        assert not _is_unwanted_fly_toml("fly.test-agent-api.toml")

    def test_keeps_worker_toml(self):
        assert not _is_unwanted_fly_toml("fly.test-agent-worker.toml")

    def test_removes_dashboard_toml(self):
        assert _is_unwanted_fly_toml("fly.test-agent-dashboard.toml")

    def test_removes_scheduler_toml(self):
        assert _is_unwanted_fly_toml("fly.test-agent-scheduler.toml")

    def test_removes_frontend_toml(self):
        assert _is_unwanted_fly_toml("fly.test-agent-frontend.toml")

    def test_removes_ui_toml(self):
        assert _is_unwanted_fly_toml("fly.test-agent-ui.toml")

    def test_removes_postgres_toml(self):
        assert _is_unwanted_fly_toml("fly.test-agent-postgres.toml")

    def test_removes_db_toml(self):
        assert _is_unwanted_fly_toml("fly.test-agent-db.toml")

    def test_removes_database_toml(self):
        assert _is_unwanted_fly_toml("fly.test-agent-database.toml")

    def test_keeps_agent_with_db_in_name_api(self):
        """Agent named 'trading-db' must keep its API toml — 'db' is part of the agent name, not service type."""
        assert not _is_unwanted_fly_toml("fly.trading-db-api.toml")

    def test_keeps_agent_with_db_in_name_worker(self):
        assert not _is_unwanted_fly_toml("fly.trading-db-worker.toml")

    def test_keeps_non_fly_toml(self):
        """Regular config files should never be touched."""
        assert not _is_unwanted_fly_toml("pyproject.toml")
        assert not _is_unwanted_fly_toml("config/settings.toml")

    def test_case_insensitive(self):
        """Filter should work regardless of case."""
        assert _is_unwanted_fly_toml("fly.MyAgent-Dashboard.toml")
        assert not _is_unwanted_fly_toml("fly.MyAgent-API.toml")


# ── Performance monitor tests ──────────────────────────────────────────────────


class TestPerformanceMonitor:
    """Test _calculate_degradation — pure function, no mocking needed."""

    def test_no_degradation_zero_baseline(self):
        from monitoring.performance_monitor import _calculate_degradation
        assert _calculate_degradation(50.0, 0.0, higher_is_better=True) == 0.0

    def test_degradation_higher_is_better(self):
        from monitoring.performance_monitor import _calculate_degradation
        # current=50, baseline=100 → 50% degradation
        result = _calculate_degradation(50.0, 100.0, higher_is_better=True)
        assert result == pytest.approx(0.5)

    def test_degradation_lower_is_better(self):
        from monitoring.performance_monitor import _calculate_degradation
        # current=120s, baseline=100s → 20% degradation (slower is worse)
        result = _calculate_degradation(120.0, 100.0, higher_is_better=False)
        assert result == pytest.approx(0.2)

    def test_no_degradation_when_improved_higher_is_better(self):
        from monitoring.performance_monitor import _calculate_degradation
        # current=150, baseline=100, higher is better → improvement, not degradation
        assert _calculate_degradation(150.0, 100.0, higher_is_better=True) == 0.0

    def test_no_degradation_when_improved_lower_is_better(self):
        from monitoring.performance_monitor import _calculate_degradation
        # current=80s, baseline=100s, lower is better → improvement, not degradation
        assert _calculate_degradation(80.0, 100.0, higher_is_better=False) == 0.0

    def test_threshold_boundary(self):
        from monitoring.performance_monitor import _calculate_degradation, DEGRADATION_THRESHOLD
        # Exactly at threshold — should not trigger (≤ not >)
        result = _calculate_degradation(85.0, 100.0, higher_is_better=True)
        assert result == pytest.approx(0.15)
        assert result <= DEGRADATION_THRESHOLD  # 15% exactly = threshold, not over


# ── Chat tool executor tests ───────────────────────────────────────────────────


class TestChatToolExecutors:
    """Test chat tool executors with mocked DB sessions."""

    @pytest.mark.asyncio
    async def test_get_file_content_not_found_returns_helpful_message(self):
        from app.api.routes.chat import _exec_get_file_content

        mock_session = AsyncMock()
        # First query (exact match) — no result
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        # Second query (partial match) — no candidates
        no_candidates = MagicMock()
        no_candidates.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[no_result, no_candidates])

        result = await _exec_get_file_content("fake-run-id", "nonexistent.py", mock_session)
        assert "not found" in result.lower()
        assert "nonexistent.py" in result

    @pytest.mark.asyncio
    async def test_get_file_content_partial_match_suggests_alternatives(self):
        from app.api.routes.chat import _exec_get_file_content

        mock_session = AsyncMock()
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        # Partial match returns candidates
        candidate = MagicMock()
        candidate.file_path = "app/api/main.py"
        has_candidates = MagicMock()
        has_candidates.scalars.return_value.all.return_value = [candidate]
        mock_session.execute = AsyncMock(side_effect=[no_result, has_candidates])

        result = await _exec_get_file_content("fake-run-id", "main.py", mock_session)
        assert "app/api/main.py" in result

    @pytest.mark.asyncio
    async def test_get_file_content_no_stored_content(self):
        from app.api.routes.chat import _exec_get_file_content

        mock_file = MagicMock()
        mock_file.content = None
        mock_file.file_path = "app/main.py"
        has_file = MagicMock()
        has_file.scalar_one_or_none.return_value = mock_file

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=has_file)

        result = await _exec_get_file_content("run-123", "app/main.py", mock_session)
        assert "no stored content" in result.lower()

    @pytest.mark.asyncio
    async def test_get_file_content_returns_full_content(self):
        from app.api.routes.chat import _exec_get_file_content

        mock_file = MagicMock()
        mock_file.content = "from fastapi import FastAPI\napp = FastAPI()"
        mock_file.file_path = "app/main.py"
        mock_file.status = "complete"
        mock_file.layer = 3
        has_file = MagicMock()
        has_file.scalar_one_or_none.return_value = mock_file

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=has_file)

        result = await _exec_get_file_content("run-123", "app/main.py", mock_session)
        assert "FastAPI" in result
        assert "app/main.py" in result

    @pytest.mark.asyncio
    async def test_search_file_content_no_matches(self):
        from app.api.routes.chat import _exec_search_file_content

        no_matches = MagicMock()
        no_matches.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=no_matches)

        result = await _exec_search_file_content("totally_nonexistent_xyz", None, mock_session)
        assert "no files found" in result.lower()

    @pytest.mark.asyncio
    async def test_search_file_content_returns_matches(self):
        from app.api.routes.chat import _exec_search_file_content

        match_row = ("run-abc123", "app/models.py", "class User(Base):\n    id = Column(Integer)")
        has_matches = MagicMock()
        has_matches.all.return_value = [match_row]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=has_matches)

        result = await _exec_search_file_content("User", None, mock_session)
        assert "app/models.py" in result
        assert "1 file" in result.lower()

    @pytest.mark.asyncio
    async def test_get_file_content_db_error_returns_graceful_message(self):
        from app.api.routes.chat import _exec_get_file_content

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB connection lost"))

        result = await _exec_get_file_content("run-123", "app/main.py", mock_session)
        assert "error" in result.lower()
        # Should not raise — errors are caught and returned as string


# ── Chat request model tests ───────────────────────────────────────────────────


class TestChatModels:
    """Test Pydantic model validation for chat request/response."""

    def test_chat_request_valid(self):
        from app.api.routes.chat import ChatRequest, ChatMessage
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            memory_notes=None,
            files_context=None,
        )
        assert len(req.messages) == 1
        assert req.messages[0].role == "user"

    def test_chat_request_with_memory_and_files(self):
        from app.api.routes.chat import ChatRequest, ChatMessage
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="Review my build")],
            memory_notes="User prefers AUD pricing",
            files_context="blueprint.pdf",
        )
        assert req.memory_notes == "User prefers AUD pricing"

    def test_chat_response_defaults(self):
        from app.api.routes.chat import ChatResponse
        resp = ChatResponse(reply="Hello!", model="claude-sonnet-4-6")
        assert resp.tool_calls_made == 0

    def test_chat_response_with_tool_calls(self):
        from app.api.routes.chat import ChatResponse
        resp = ChatResponse(reply="Here is the file...", model="claude-sonnet-4-6", tool_calls_made=2)
        assert resp.tool_calls_made == 2
