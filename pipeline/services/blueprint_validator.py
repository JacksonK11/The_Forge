"""
pipeline/services/blueprint_validator.py
Scores the blueprint BEFORE parsing. Identifies ambiguities and missing info.
Auto-resolves common gaps so Claude generates better specs from enhanced blueprints.

Score thresholds:
  < 40: reject — blueprint too vague to build
  40-70: auto-resolve ambiguities, use enhanced blueprint for parsing
  > 70: proceed normally, include summary in spec review
"""

import json
import re

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings

_VALIDATE_PROMPT = """\
Score this AI agent blueprint on completeness (0-100). Check for:
1. Database: Are all tables and columns explicitly defined?
2. APIs: Are all external APIs listed with their purpose?
3. Routes: Are all API endpoints described with request/response shapes?
4. Events: Are all triggers (webhooks, schedules, user actions) specified?
5. Dashboard: Are all screens described with their data sources?
6. Deployment: Is Fly.io region, machine size, and service count specified?
7. Secrets: Are all required API keys and env vars mentioned?

Return JSON only (no markdown):
{"score": 0-100, "ambiguities": [{"area": "str", "issue": "str", "suggestion": "str", "auto_resolvable": true/false}], "assumptions": [{"area": "str", "assumption": "str"}], "missing": [{"area": "str", "what": "str", "impact": "str"}]}
"""

_SAFE_DEFAULT = {
    "score": 75,
    "ambiguities": [],
    "assumptions": [],
    "missing": [],
}


class BlueprintValidator:
    """
    Scores and enriches blueprints before they are parsed into build specs.
    """

    async def validate(self, blueprint_text: str) -> dict:
        """
        Score a blueprint on completeness and identify ambiguities.

        Args:
            blueprint_text: Raw blueprint text submitted by the user.

        Returns:
            {
                'score': int,
                'ambiguities': [{'area', 'issue', 'suggestion', 'auto_resolvable'}],
                'assumptions': [{'area', 'assumption'}],
                'missing': [{'area', 'what', 'impact'}],
            }
            Falls back to safe defaults on any failure.
        """
        try:
            truncated = blueprint_text[:6000]
            model_id = router.get_model("blueprint_validation")

            user_message = f"{_VALIDATE_PROMPT}\n\nBLUEPRINT:\n{truncated}"

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            message = await client.messages.create(
                model=model_id,
                max_tokens=1024,
                messages=[{"role": "user", "content": user_message}],
            )

            raw = ""
            if message.content:
                raw = message.content[0].text.strip()

            # Strip any accidental markdown fences
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                # Try to extract just the JSON object if there's surrounding text
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    try:
                        result = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[blueprint_validator] Could not parse Claude response as JSON. "
                            f"raw={raw[:200]}"
                        )
                        return dict(_SAFE_DEFAULT)
                else:
                    logger.warning(
                        f"[blueprint_validator] No JSON object found in Claude response. "
                        f"raw={raw[:200]}"
                    )
                    return dict(_SAFE_DEFAULT)

            # Validate and normalise fields
            score = result.get("score", 75)
            if not isinstance(score, (int, float)):
                score = 75
            score = max(0, min(100, int(score)))

            validated = {
                "score": score,
                "ambiguities": result.get("ambiguities", []) if isinstance(result.get("ambiguities"), list) else [],
                "assumptions": result.get("assumptions", []) if isinstance(result.get("assumptions"), list) else [],
                "missing": result.get("missing", []) if isinstance(result.get("missing"), list) else [],
            }

            logger.info(
                f"[blueprint_validator] score={score} "
                f"ambiguities={len(validated['ambiguities'])} "
                f"missing={len(validated['missing'])}"
            )

            return validated

        except anthropic.APIError as exc:
            logger.warning(f"[blueprint_validator] Anthropic API error during validate: {exc}")
            return dict(_SAFE_DEFAULT)
        except Exception as exc:
            logger.warning(f"[blueprint_validator] Unexpected error during validate: {exc}")
            return dict(_SAFE_DEFAULT)

    async def auto_resolve(self, blueprint_text: str, validation_result: dict) -> str:
        """
        Append auto-resolvable assumptions to the blueprint text.

        Args:
            blueprint_text: Original blueprint text.
            validation_result: The dict returned by validate().

        Returns:
            Enhanced blueprint text with assumptions appended, or original if none.
        """
        try:
            ambiguities = validation_result.get("ambiguities", [])
            resolvable = [a for a in ambiguities if a.get("auto_resolvable") is True]

            if not resolvable:
                return blueprint_text

            lines: list[str] = ["\n\n--- AUTO-RESOLVED ASSUMPTIONS (added by The Forge) ---\n"]
            for item in resolvable:
                area = item.get("area", "General")
                suggestion = item.get("suggestion", "")
                if suggestion:
                    lines.append(f"- {area}: {suggestion}\n")

            assumptions_block = "".join(lines)
            enhanced = blueprint_text + assumptions_block

            logger.info(
                f"[blueprint_validator] auto_resolve appended {len(resolvable)} assumptions"
            )

            return enhanced

        except Exception as exc:
            logger.warning(f"[blueprint_validator] auto_resolve failed: {exc}")
            return blueprint_text

    def format_for_spec_review(self, validation_result: dict) -> str:
        """
        Format a short human-readable summary of the validation result.

        Args:
            validation_result: The dict returned by validate().

        Returns:
            Multi-line string suitable for embedding in a spec review report.
        """
        try:
            score = validation_result.get("score", 75)
            ambiguities = validation_result.get("ambiguities", [])
            missing = validation_result.get("missing", [])

            resolvable_count = sum(
                1 for a in ambiguities if a.get("auto_resolvable") is True
            )
            missing_count = len(missing)

            lines: list[str] = [f"BLUEPRINT QUALITY: {score}/100"]

            if resolvable_count:
                lines.append(f"AUTO-RESOLVED: {resolvable_count} ambiguities")

            if missing_count:
                lines.append(f"FLAGGED: {missing_count} items need attention")
                for item in missing[:3]:
                    area = item.get("area", "Unknown")
                    what = item.get("what", "")
                    lines.append(f"  - {area}: {what}")

            return "\n".join(lines)

        except Exception as exc:
            logger.warning(f"[blueprint_validator] format_for_spec_review failed: {exc}")
            return "BLUEPRINT QUALITY: unknown"
