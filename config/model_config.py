"""
config/model_config.py
Routes Claude API calls to the appropriate model based on task type.

Strategy (Part E — Cost Optimisation):
  claude-sonnet-4-6           → generation, architecture, synthesis, parsing, verification
  claude-haiku-4-5-20251001   → evaluation, validation, classification, scoring, summarisation
  claude-opus-4-6             → NEVER used in The Forge pipeline. Sonnet handles everything.

This routing reduces API costs 35-40% vs all-Sonnet, while maintaining full quality.
Every Claude call is logged with model, task_type, token counts, and cost in USD + AUD.

Usage:
    from config.model_config import router
    model = router.get_model("generation")   # → "claude-sonnet-4-6"
    model = router.get_model("evaluation")   # → "claude-haiku-4-5-20251001"
    cost = router.estimate_cost(model, input_tokens=2000, output_tokens=500)
"""

from dataclasses import dataclass, field
from typing import Optional

from config.settings import settings

# ── Pricing (USD per million tokens, as of Q1 2026) ──────────────────────────

PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25},
    # Opus listed for reference only — should never appear in build_costs table
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
}

# AUD conversion rate (approximate Q1 2026 — update quarterly)
_USD_TO_AUD = 1.58

# Alert threshold: send Telegram if a single build exceeds this AUD cost
BUILD_COST_ALERT_AUD = 8.0

# ── Task → Model routing ──────────────────────────────────────────────────────

# High-quality tasks → Sonnet (reasoning, generation, synthesis)
_SONNET_TASKS = frozenset([
    "generation",
    "architecture",
    "synthesis",
    "parsing",
    "verification",
    "reasoning",
    "readme",
    "secrets",
    "meta_rules",
    "research",
    "strategy",
    "change_spec",
    "apply_changes",
    "deploy_fix",
])

# Fast tasks → Haiku (classification, checking, scoring — cheap, low latency)
_HAIKU_TASKS = frozenset([
    "evaluation",
    "validation",
    "classification",
    "scoring",
    "checking",
    "summarisation",
    "intent_detection",
    "blueprint_validation",
    "blueprint_scoring",
    "diagnosis",
    "wiring_check",
    "endpoint_test",
])


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class ModelSelection:
    model: str
    task_type: str
    estimated_cost_usd: float = 0.0


@dataclass
class UsageRecord:
    model: str
    task_type: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_aud: float
    run_id: Optional[str] = None
    stage: Optional[str] = None
    file_path: Optional[str] = None


# ── Model router ──────────────────────────────────────────────────────────────


class ModelRouter:
    """
    Routes Claude calls to Sonnet or Haiku based on task type.
    Tracks cumulative token usage and costs for the performance monitor and dashboard.
    Logs model used for every call so cost is fully auditable.
    Never routes to Opus.
    """

    def __init__(self) -> None:
        self._usage_log: list[UsageRecord] = []
        self._total_cost_usd: float = 0.0
        self._total_cost_aud: float = 0.0

    def get_model(self, task_type: str) -> str:
        """Return the appropriate Claude model ID for the given task type. Never returns Opus."""
        if task_type in _HAIKU_TASKS:
            model = settings.claude_fast_model
        else:
            model = settings.claude_model

        # Safety guard: reject Opus at routing layer
        if "opus" in model.lower():
            import logging
            logging.warning(
                f"BLOCKED: Opus model requested for task_type='{task_type}'. "
                f"Routing to Sonnet instead."
            )
            model = "claude-sonnet-4-6"

        return model

    def select(self, task_type: str) -> ModelSelection:
        """Return a ModelSelection for the given task type."""
        return ModelSelection(model=self.get_model(task_type), task_type=task_type)

    def estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Estimate API cost in USD for a given model and token counts."""
        pricing = PRICING.get(model, PRICING["claude-sonnet-4-6"])
        return (
            input_tokens * pricing["input"] + output_tokens * pricing["output"]
        ) / 1_000_000

    def usd_to_aud(self, usd: float) -> float:
        """Convert USD to AUD using current conversion rate."""
        return round(usd * _USD_TO_AUD, 6)

    def record_usage(
        self,
        model: str,
        task_type: str,
        input_tokens: int,
        output_tokens: int,
        run_id: Optional[str] = None,
        stage: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> float:
        """
        Record token usage and return cost in USD.
        Logs which model was used so Haiku vs Sonnet routing is auditable.
        """
        cost_usd = self.estimate_cost(model, input_tokens, output_tokens)
        cost_aud = self.usd_to_aud(cost_usd)

        record = UsageRecord(
            model=model,
            task_type=task_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            cost_aud=cost_aud,
            run_id=run_id,
            stage=stage,
            file_path=file_path,
        )
        self._usage_log.append(record)
        self._total_cost_usd += cost_usd
        self._total_cost_aud += cost_aud

        # Structured log line — visible in Fly.io logs and searchable
        from loguru import logger
        logger.debug(
            f"model_usage | model={model} task={task_type} "
            f"in={input_tokens} out={output_tokens} "
            f"cost_usd={cost_usd:.5f} cost_aud={cost_aud:.5f}"
            + (f" run_id={run_id}" if run_id else "")
            + (f" stage={stage}" if stage else "")
            + (f" file={file_path}" if file_path else "")
        )

        return cost_usd

    async def persist_cost(
        self,
        run_id: str,
        stage: str,
        model: str,
        task_type: str,
        input_tokens: int,
        output_tokens: int,
        file_path: Optional[str] = None,
    ) -> float:
        """
        Persist a single Claude call cost to the build_costs table and return cost_usd.
        Non-blocking — errors are logged but never raised.
        """
        cost_usd = self.estimate_cost(model, input_tokens, output_tokens)
        cost_aud = self.usd_to_aud(cost_usd)

        try:
            from memory.database import get_session
            from memory.models import BuildCost

            async with get_session() as session:
                record = BuildCost(
                    run_id=run_id,
                    stage=stage,
                    file_path=file_path,
                    model=model,
                    task_type=task_type,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    cost_aud=cost_aud,
                )
                session.add(record)
        except Exception as exc:
            from loguru import logger
            logger.warning(f"Failed to persist build cost (non-blocking): {exc}")

        # Alert if this build is getting expensive
        if run_id:
            await self._check_build_cost_alert(run_id)

        return cost_usd

    async def _check_build_cost_alert(self, run_id: str) -> None:
        """Send Telegram alert if this build's total cost exceeds $8 AUD."""
        try:
            from memory.database import get_session
            from memory.models import BuildCost
            from sqlalchemy import func, select

            async with get_session() as session:
                result = await session.execute(
                    select(func.sum(BuildCost.cost_aud)).where(
                        BuildCost.run_id == run_id
                    )
                )
                total_aud = result.scalar_one() or 0.0

            if total_aud >= BUILD_COST_ALERT_AUD:
                from app.api.services.notify import _send
                from loguru import logger
                logger.warning(
                    f"[{run_id}] Build cost alert: A${total_aud:.2f} >= A${BUILD_COST_ALERT_AUD:.2f}"
                )
                await _send(
                    f"⚠️ <b>The Forge — High Build Cost Alert</b>\n\n"
                    f"Run ID: <code>{run_id}</code>\n"
                    f"Total cost so far: <b>A${total_aud:.2f}</b>\n"
                    f"Alert threshold: A${BUILD_COST_ALERT_AUD:.2f}"
                )
        except Exception:
            pass  # Non-blocking

    def get_session_cost(self) -> float:
        """Total API cost in USD accumulated since this router instance was created."""
        return self._total_cost_usd

    def get_session_cost_aud(self) -> float:
        """Total API cost in AUD accumulated since this router instance was created."""
        return self._total_cost_aud

    def get_usage_summary(self) -> dict:
        """Summary of token usage grouped by model and task type."""
        summary: dict[str, dict] = {}
        for record in self._usage_log:
            key = f"{record.model}:{record.task_type}"
            if key not in summary:
                summary[key] = {
                    "model": record.model,
                    "task_type": record.task_type,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "cost_aud": 0.0,
                }
            summary[key]["calls"] += 1
            summary[key]["input_tokens"] += record.input_tokens
            summary[key]["output_tokens"] += record.output_tokens
            summary[key]["cost_usd"] += record.cost_usd
            summary[key]["cost_aud"] += record.cost_aud
        return summary

    def reset(self) -> None:
        """Reset usage tracking (called between builds in long-running processes)."""
        self._usage_log.clear()
        self._total_cost_usd = 0.0
        self._total_cost_aud = 0.0


# ── Singleton ─────────────────────────────────────────────────────────────────

router = ModelRouter()
