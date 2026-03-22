"""
intelligence/meta_rules.py
Weekly job that extracts operational rules from real build outcomes.

Every Sunday at midnight, this module:
  1. Reads the last 50 build outcomes from the knowledge base
  2. Calls Claude Sonnet to extract new operational rules
  3. Saves new rules to MetaRule table
  4. Deactivates rules that are superseded or incorrect
  5. Sends a Telegram summary of changes

The extracted rules are injected into every subsequent build prompt via
context_assembler.py — the agent self-improves without any code changes.

After 20 builds, The Forge generates meaningfully better code than on build 1.
"""

import json

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.model_config import router
from config.settings import settings
from intelligence.knowledge_base import get_recent_outcomes
from memory.database import get_session
from memory.models import MetaRule
from pipeline.prompts.prompts import META_RULES_SYSTEM, META_RULES_USER

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def extract_and_update_rules() -> dict:
    """
    Main entry point for the weekly meta-rules extraction job.
    Returns a summary dict with counts of new/retired rules.
    """
    logger.info("Meta-rules extraction started")

    outcomes = await get_recent_outcomes(limit=50)
    if len(outcomes) < 5:
        logger.info(f"Not enough outcomes for meta-rules extraction ({len(outcomes)} < 5). Skipping.")
        return {"new_rules": 0, "retired_rules": 0, "skipped": True}

    outcomes_text = "\n\n".join(
        f"[{o['type']} | {o['outcome']}] {o['content']}"
        for o in outcomes
    )

    try:
        result = await retry_async(
            _call_claude_for_rules,
            outcomes_text,
            max_attempts=3,
            label="meta_rules_extraction",
        )
    except Exception as exc:
        logger.error(f"Meta-rules extraction failed: {exc}")
        return {"new_rules": 0, "retired_rules": 0, "error": str(exc)}

    new_count = await _save_new_rules(result.get("new_rules", []))
    retired_count = await _retire_rules(result.get("rules_to_retire", []))

    summary = {
        "new_rules": new_count,
        "retired_rules": retired_count,
        "outcomes_analysed": len(outcomes),
    }

    logger.info(
        f"Meta-rules extraction complete: {new_count} new rules, {retired_count} retired"
    )

    try:
        await _notify_rules_update(summary)
    except Exception as exc:
        logger.warning(f"Meta-rules notification failed (non-blocking): {exc}")

    return summary


async def get_active_rules() -> list[str]:
    """
    Return all active meta-rules as a list of rule text strings.
    Called by context_assembler.py before every major Claude call.
    """
    try:
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(MetaRule)
                .where(MetaRule.is_active == True)
                .order_by(MetaRule.confidence.desc(), MetaRule.applied_count.desc())
                .limit(15)
            )
            rules = result.scalars().all()
            return [r.rule_text for r in rules]
    except Exception as exc:
        logger.warning(f"get_active_rules failed: {exc}")
        return []


async def increment_rule_usage(rule_texts: list[str]) -> None:
    """
    Increment applied_count for rules that were used in a build.
    Called after each successful build that used meta-rules.
    """
    if not rule_texts:
        return
    try:
        from sqlalchemy import update
        async with get_session() as session:
            for rule_text in rule_texts:
                await session.execute(
                    update(MetaRule)
                    .where(MetaRule.rule_text == rule_text)
                    .values(applied_count=MetaRule.applied_count + 1)
                )
    except Exception as exc:
        logger.warning(f"increment_rule_usage failed (non-blocking): {exc}")


# ── Internal ──────────────────────────────────────────────────────────────────


async def _call_claude_for_rules(outcomes_text: str) -> dict:
    """Call Claude Sonnet to extract rules from build outcomes."""
    model = router.get_model("meta_rules")
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=META_RULES_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": META_RULES_USER.format(outcomes=outcomes_text[:12000]),
            }
        ],
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


async def _save_new_rules(new_rules: list[dict]) -> int:
    """Save new rules to MetaRule table. Skips duplicates."""
    if not new_rules:
        return 0

    saved = 0
    async with get_session() as session:
        from sqlalchemy import select
        for rule_data in new_rules:
            rule_text = rule_data.get("rule_text", "").strip()
            if not rule_text:
                continue

            existing = await session.execute(
                select(MetaRule).where(MetaRule.rule_text == rule_text)
            )
            if existing.scalar_one_or_none():
                continue

            session.add(
                MetaRule(
                    rule_type=rule_data.get("rule_type", "generation"),
                    rule_text=rule_text,
                    confidence=float(rule_data.get("confidence", 0.8)),
                    is_active=True,
                )
            )
            saved += 1
    logger.info(f"Saved {saved} new meta-rules")
    return saved


async def _retire_rules(rules_to_retire: list[str]) -> int:
    """Deactivate rules that are superseded or known incorrect."""
    if not rules_to_retire:
        return 0

    retired = 0
    async with get_session() as session:
        from sqlalchemy import update
        for rule_text in rules_to_retire:
            result = await session.execute(
                update(MetaRule)
                .where(MetaRule.rule_text == rule_text, MetaRule.is_active == True)
                .values(is_active=False)
            )
            retired += result.rowcount

    logger.info(f"Retired {retired} meta-rules")
    return retired


async def _notify_rules_update(summary: dict) -> None:
    """Send Telegram notification about weekly meta-rules update."""
    from app.api.services.notify import _send
    text = (
        f"🧠 <b>The Forge — Meta-Rules Updated</b>\n\n"
        f"Outcomes analysed: <b>{summary.get('outcomes_analysed', 0)}</b>\n"
        f"New rules added: <b>{summary.get('new_rules', 0)}</b>\n"
        f"Rules retired: <b>{summary.get('retired_rules', 0)}</b>\n\n"
        f"The Forge's generation prompts have been updated automatically."
    )
    await _send(text)
