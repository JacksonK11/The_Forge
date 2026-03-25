"""
pipeline/quality/blueprint_validator.py
Enhanced blueprint pre-validation before the expensive Sonnet parsing call.

Uses Claude Haiku to check blueprint completeness and specificity.
A vague or incomplete blueprint wastes expensive Sonnet tokens and produces
a poor spec. This module catches problems upfront for fractions of a penny.

Checks performed:
  1. Does it describe what the agent actually does?
  2. Does it mention at least one database table with column descriptions?
  3. Does it describe at least one API endpoint or background job?
  4. Are the database columns described specifically (not just table names)?
  5. Is the dashboard/UI described (if applicable)?
  6. Are external service integrations mentioned?
  7. Is it specific enough for code generation (vs a high-level idea)?

Used by parse_node.py — replaces the simpler inline validation.
"""

import json
from dataclasses import dataclass, field

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

VALIDATION_SYSTEM = """You are a blueprint validator for The Forge, an AI code generation engine.
Your job is to check if a blueprint document is complete and specific enough to
generate a production-ready codebase from.

A good blueprint provides enough detail that an engineer could start coding immediately.
A bad blueprint is too high-level, missing database details, or too vague about what the system does.

Be strict. Vague blueprints produce vague code."""

VALIDATION_USER = """Evaluate this blueprint document for code generation readiness.

BLUEPRINT:
{blueprint_text}

Answer these specific questions about the blueprint:
1. Does it clearly state what problem this agent solves and what it does?
2. Does it include at least one specific database table (not just "database")?
3. Do the database tables have column descriptions (not just table names)?
4. Does it describe at least one specific API endpoint with method and purpose?
5. Is the tech stack implied or specified (Python/FastAPI, React, etc.)?
6. Are any external service integrations mentioned (Anthropic, Twilio, etc.)?

Respond with JSON only:
{{
  "is_valid": true/false,
  "completeness_score": 0-10,
  "missing_elements": ["specific things that are missing"],
  "questions_for_user": ["specific questions to ask the user to fill gaps"],
  "suggestions": ["suggestions to improve the blueprint"],
  "can_proceed_with_warnings": true/false
}}

Scoring guide:
  8-10: Ready to generate — complete and specific
  5-7:  Can proceed with warnings — some gaps but enough to work with
  0-4:  Too incomplete — requires user input before proceeding"""


@dataclass
class ValidationResult:
    is_valid: bool
    completeness_score: int
    missing_elements: list[str] = field(default_factory=list)
    questions_for_user: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    can_proceed_with_warnings: bool = True
    raw_response: dict = field(default_factory=dict)

    def to_error_message(self) -> str:
        """Format as a user-facing error message."""
        parts = []
        if self.missing_elements:
            parts.append("Missing: " + ", ".join(self.missing_elements))
        if self.questions_for_user:
            parts.append("Please address: " + " | ".join(self.questions_for_user))
        return ". ".join(parts) if parts else "Blueprint is too incomplete for code generation."


async def validate_blueprint(blueprint_text: str) -> ValidationResult:
    """
    Validate a blueprint document for code generation readiness.

    Args:
        blueprint_text: The raw blueprint text submitted by the user.

    Returns:
        ValidationResult indicating whether to proceed and what's missing.
    """
    if len(blueprint_text.strip()) < 100:
        return ValidationResult(
            is_valid=False,
            completeness_score=0,
            missing_elements=["Blueprint text is too short"],
            questions_for_user=[
                "What does this agent do?",
                "What database tables does it need?",
                "What API endpoints does it expose?",
            ],
            can_proceed_with_warnings=False,
        )

    model = router.get_model("blueprint_validation")
    try:
        response = client.messages.create(
            model=model,
            max_tokens=800,
            system=VALIDATION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": VALIDATION_USER.format(
                        blueprint_text=blueprint_text[:8000]
                    ),
                }
            ],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        raw = json.loads(text)

        score = raw.get("completeness_score", 5)
        return ValidationResult(
            is_valid=raw.get("is_valid", score >= 5),
            completeness_score=score,
            missing_elements=raw.get("missing_elements", []),
            questions_for_user=raw.get("questions_for_user", []),
            suggestions=raw.get("suggestions", []),
            can_proceed_with_warnings=raw.get("can_proceed_with_warnings", score >= 5),
            raw_response=raw,
        )

    except json.JSONDecodeError as exc:
        logger.warning(f"Blueprint validation response not JSON: {exc}")
        # Default to valid — don't block on validator errors
        return ValidationResult(is_valid=True, completeness_score=6)
    except Exception as exc:
        logger.error(f"Blueprint validation error: {exc}")
        return ValidationResult(is_valid=True, completeness_score=6)
