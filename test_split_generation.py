"""
test_split_generation.py
Smoke test for split generation logic.

Runs _generate_file_split against a known large file spec (execution.py style —
trading execution engine, ~400 lines) using real Claude API calls.

Validates:
  - Output is syntactically valid Python (ast.parse)
  - No truncation detected (_detect_truncation)
  - Total tokens + estimated cost printed
  - Clear PASS / FAIL result

Usage:
    python test_split_generation.py

Requirements:
    - ANTHROPIC_API_KEY set in .env (loaded automatically)
    - No running DB/Redis needed — persist_cost is patched out
"""

import ast
import asyncio
import sys
import time
import unittest.mock
from pathlib import Path

# ── Bootstrap: add project root to sys.path ───────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Load .env so settings picks up ANTHROPIC_API_KEY and CLAUDE_MODEL
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ── Stub out DB/infrastructure modules before any project imports ─────────────
# layer_generator.py has module-level imports from memory.* and knowledge.*
# which pull in pgvector, sqlalchemy, asyncpg, etc. We don't need any of that
# for a pure generation smoke test — stub them out with minimal mocks.

import types

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod

# pgvector.sqlalchemy — only used for Vector column type in models.py
_pgvector_sa = _make_stub("pgvector")
_pgvector_sa.sqlalchemy = _make_stub("pgvector.sqlalchemy")
_pgvector_sa.sqlalchemy.Vector = lambda *a, **kw: None  # type: ignore[attr-defined]

# memory.models — need FileStatus and ForgeFile as simple stubs
_mem_models = _make_stub("memory.models")
_mem_models.FileStatus = type("FileStatus", (), {"COMPLETE": type("_v", (), {"value": "complete"})()})  # type: ignore[attr-defined]
_mem_models.ForgeFile = type("ForgeFile", (), {})  # type: ignore[attr-defined]
_mem_models.MetaRule = type("MetaRule", (), {})  # type: ignore[attr-defined]

# memory.database — get_session never called in our test path
_mem_db = _make_stub("memory.database")
_mem_db.get_session = None  # type: ignore[attr-defined]

# knowledge.retriever — called at runtime in _get_knowledge_context but we pass "" directly
_know_ret = _make_stub("knowledge.retriever")
async def _stub_retrieve(*a, **kw): return []
_know_ret.retrieve_relevant_chunks = _stub_retrieve  # type: ignore[attr-defined]

# sqlalchemy stubs (needed by memory.models on import)
for _mod_name in ["sqlalchemy", "sqlalchemy.orm", "sqlalchemy.ext.asyncio",
                   "sqlalchemy.dialects.postgresql", "asyncpg"]:
    if _mod_name not in sys.modules:
        _make_stub(_mod_name)

# ── Patch DB calls before importing layer_generator ───────────────────────────
# persist_cost hits Postgres — patch it to a no-op BEFORE model_config loads.
# record_usage is in-memory only and must NOT be patched (we need the cost data).
async def _noop_persist(*args, **kwargs) -> float:
    return 0.0

import config.model_config as _model_config_mod
_model_config_mod.ModelRouter.persist_cost = _noop_persist  # type: ignore[method-assign]

# ── Now safe to import pipeline modules ───────────────────────────────────────
from config.model_config import router as model_router
from pipeline.nodes.layer_generator import (
    _detect_truncation,
    _generate_file_split,
    _is_complex_file,
)

# ── Test fixture: execution.py-style spec ─────────────────────────────────────

TEST_RUN_ID = "test-smoke-001"

TEST_FILE_ENTRY = {
    "path": "backend/execution.py",
    "layer": 4,
    "description": (
        "Trading execution engine. Manages order lifecycle: PENDING → OPEN → CLOSED. "
        "Handles position sizing (1% risk per trade), SL/TP placement, partial fills, "
        "slippage tracking, and reconciliation against broker. "
        "Key classes: ExecutionEngine, OrderManager, PositionTracker. "
        "Key functions: submit_order, cancel_order, reconcile_positions, "
        "calculate_position_size, get_open_positions, close_all_positions. "
        "Uses Alpaca REST API for order submission. Full async. "
        "Loguru logging on every state transition."
    ),
    "estimated_lines": 400,
}

TEST_SPEC = {
    "agent_name": "Trading OS",
    "agent_slug": "trading-os",
    "description": "Fully autonomous trading research and execution system for prop firm accounts.",
    "stack": "Python 3.12, FastAPI, LangGraph, asyncpg, RQ, Alpaca API",
    "services": ["api", "worker", "scheduler"],
    "database": {
        "tables": ["orders", "positions", "trades", "strategies", "performance_metrics"]
    },
    "intelligence": {
        "models": {
            "reasoning": "claude-opus-4-6",
            "research": "claude-sonnet-4-6",
            "classification": "claude-haiku-4-5-20251001",
        }
    },
    "broker": "Alpaca",
    "risk": {
        "max_risk_per_trade_pct": 1.0,
        "max_open_positions": 3,
        "daily_loss_limit_pct": 1.0,
        "weekly_loss_limit_pct": 2.0,
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _print_section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _check_syntax(content: str) -> tuple[bool, str]:
    """Returns (passed, error_message)."""
    try:
        ast.parse(content)
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"


def _check_no_truncation(content: str, file_path: str) -> tuple[bool, str]:
    """Returns (passed, reason). Passed=True means NOT truncated."""
    if _detect_truncation(content, file_path):
        # Peek at the last 3 lines for diagnosis
        last_lines = "\n".join(content.splitlines()[-3:])
        return False, f"Truncation detected. Last 3 lines:\n{last_lines}"
    return True, ""


def _print_cost_summary() -> None:
    summary = model_router.get_usage_summary()
    total_aud = model_router.get_session_cost_aud()

    if not summary:
        print("  No usage recorded (model_router.record_usage not called?)")
        return

    for key, data in sorted(summary.items()):
        print(
            f"  {data['model']} [{data['task_type']}]: "
            f"{data['calls']} calls, "
            f"{data['input_tokens']:,} in / {data['output_tokens']:,} out tokens, "
            f"A${data['cost_aud']:.4f}"
        )

    print(f"\n  TOTAL: A${total_aud:.4f}")


# ── Main test ─────────────────────────────────────────────────────────────────


async def run_test() -> bool:
    """Run the smoke test. Returns True on PASS, False on FAIL."""

    _print_section("Setup")
    file_path = TEST_FILE_ENTRY["path"]
    purpose = TEST_FILE_ENTRY["description"]
    estimated_lines = TEST_FILE_ENTRY["estimated_lines"]

    is_complex = _is_complex_file(file_path, purpose, estimated_lines)
    print(f"  File:        {file_path}")
    print(f"  Purpose:     {purpose[:80]}...")
    print(f"  Est. lines:  {estimated_lines}")
    print(f"  Is complex:  {is_complex}  (expected: True)")

    if not is_complex:
        print("\n  WARNING: _is_complex_file returned False — keyword/line detection may be broken")

    _print_section("Running split generation (2 real Claude API calls)...")
    t0 = time.time()

    content = await _generate_file_split(
        run_id=TEST_RUN_ID,
        file_path=file_path,
        file_entry=TEST_FILE_ENTRY,
        spec=TEST_SPEC,
        generated_files={},
        meta_rules=[],
        knowledge_context="",
    )

    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s")

    _print_section("Token usage & cost")
    _print_cost_summary()

    _print_section("Validation")

    results: list[tuple[str, bool, str]] = []

    # Check 1: content was returned
    if not content:
        results.append(("Content returned", False, "_generate_file_split returned None"))
    else:
        line_count = len(content.splitlines())
        char_count = len(content)
        results.append(("Content returned", True, f"{line_count} lines, {char_count:,} chars"))

    if content:
        # Check 2: syntax valid
        syntax_ok, syntax_err = _check_syntax(content)
        results.append(("Syntax valid (ast.parse)", syntax_ok, syntax_err or "Clean parse"))

        # Check 3: no truncation
        trunc_ok, trunc_reason = _check_no_truncation(content, file_path)
        results.append(("No truncation detected", trunc_ok, trunc_reason or "Looks complete"))

        # Check 4: file has meaningful content (not a stub)
        has_substance = len(content.strip()) > 500 and "pass" not in content[:200]
        results.append((
            "Substantial content (>500 chars, no early stub)",
            has_substance,
            f"{len(content.strip())} chars" if has_substance else "Content too short or stubbed",
        ))

        # Check 5: no duplicate import block (merge worked)
        import_lines = [ln.strip() for ln in content.splitlines() if ln.strip().startswith(("import ", "from "))]
        duplicate_imports = len(import_lines) != len(set(import_lines))
        results.append((
            "No duplicate imports (_merge_split_parts worked)",
            not duplicate_imports,
            "Clean" if not duplicate_imports else f"Found duplicates: {set(x for x in import_lines if import_lines.count(x) > 1)}",
        ))

    all_passed = all(passed for _, passed, _ in results)

    for check_name, passed, detail in results:
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {check_name}")
        if detail:
            print(f"       {detail}")

    _print_section("Result")
    if all_passed:
        print("  ✅  PASS — split generation is working correctly")
    else:
        print("  ❌  FAIL — one or more checks failed (see above)")
        failed_checks = [name for name, passed, _ in results if not passed]
        print(f"  Failed: {', '.join(failed_checks)}")

    if content:
        print("\n  Generated file preview (first 20 lines):")
        for i, line in enumerate(content.splitlines()[:20], 1):
            print(f"  {i:>3}│ {line}")
        if len(content.splitlines()) > 20:
            print(f"  ... ({len(content.splitlines()) - 20} more lines)")

    return all_passed


if __name__ == "__main__":
    passed = asyncio.run(run_test())
    sys.exit(0 if passed else 1)
