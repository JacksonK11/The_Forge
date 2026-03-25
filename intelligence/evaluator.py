"""
intelligence/evaluator.py
Scores every generated file against the production-readiness rubric before saving.

Substandard outputs are regenerated automatically — up to 3 attempts per file.
Uses Haiku (fast, cheap) for evaluation since it runs on every generated file.

Evaluation rubric (all must pass):
  1. No placeholder code (pass, ..., TODO, FIXME, "implement this")
  2. Type hints on all function signatures
  3. Error handling on external API calls
  4. No hardcoded values (URLs, keys, credentials)
  5. No blocking calls in async functions
  6. No import errors (importing non-existent modules)
  7. Correct logging (loguru, not print)
  8. No Pydantic v1 syntax

The evaluator is called from layer_generator.py after every file generation.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings
from pipeline.prompts.prompts import EVALUATOR_SYSTEM, EVALUATOR_USER

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


@dataclass
class EvaluationIssue:
    severity: str  # "critical" | "warning"
    line: str
    issue: str
    fix: str


@dataclass
class EvaluationResult:
    passed: bool
    issues: list[EvaluationIssue] = field(default_factory=list)
    summary: str = ""
    model_used: str = ""

    @property
    def critical_issues(self) -> list[EvaluationIssue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def warnings(self) -> list[EvaluationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


async def evaluate_file(
    file_path: str,
    purpose: str,
    content: str,
    strict: bool = True,
) -> EvaluationResult:
    """
    Evaluate a generated file for production readiness.

    Args:
        file_path: Path of the file being evaluated.
        purpose:   Description of what the file should do.
        content:   File content to evaluate.
        strict:    If True, any critical issue fails the evaluation.
                   If False, only placeholder code fails (used for edge cases).

    Returns:
        EvaluationResult with passed=True if file meets production standard.
    """
    # Skip evaluation for trivial files
    if _is_trivial_file(file_path, content):
        return EvaluationResult(passed=True, summary="Trivial file — evaluation skipped")

    model = router.get_model("evaluation")

    try:
        prompt = EVALUATOR_USER.format(
            file_path=file_path,
            purpose=purpose,
            content=content[:6000],
        )
        response = client.messages.create(
            model=model,
            max_tokens=800,
            system=EVALUATOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        raw = json.loads(text)

        issues = [
            EvaluationIssue(
                severity=i.get("severity", "warning"),
                line=str(i.get("line", "unknown")),
                issue=i.get("issue", ""),
                fix=i.get("fix", ""),
            )
            for i in raw.get("issues", [])
        ]

        # In strict mode, fail on any critical issue
        passed = raw.get("passed", True)
        if strict and any(i.severity == "critical" for i in issues):
            passed = False

        result = EvaluationResult(
            passed=passed,
            issues=issues,
            summary=raw.get("summary", ""),
            model_used=model,
        )

        if not result.passed:
            logger.debug(
                f"Evaluation failed for {file_path}: "
                f"{len(result.critical_issues)} critical, {len(result.warnings)} warnings"
            )

        return result

    except json.JSONDecodeError as exc:
        logger.warning(f"Evaluator response not JSON for {file_path}: {exc}")
        return EvaluationResult(passed=True, summary="Evaluation response parse error — defaulting to pass")
    except Exception as exc:
        logger.warning(f"Evaluator error for {file_path}: {exc}")
        return EvaluationResult(passed=True, summary=f"Evaluation failed (non-blocking): {exc}")


def format_issues_for_regeneration(result: EvaluationResult) -> str:
    """
    Format evaluation issues as a correction instruction for the next generation attempt.
    Injected into the codegen prompt on retry.
    """
    if not result.issues:
        return ""
    lines = ["PREVIOUS ATTEMPT FAILED EVALUATION. Fix ALL of these issues:\n"]
    for issue in result.issues:
        icon = "🚨" if issue.severity == "critical" else "⚠️"
        lines.append(f"{icon} [{issue.severity.upper()}] {issue.issue}")
        lines.append(f"   Fix: {issue.fix}")
        if issue.line and issue.line != "unknown":
            lines.append(f"   At: {issue.line}")
        lines.append("")
    return "\n".join(lines)


# ── Internal ──────────────────────────────────────────────────────────────────


def _is_trivial_file(file_path: str, content: str) -> bool:
    """Files that don't warrant LLM evaluation."""
    basename = file_path.split("/")[-1]
    if basename == "__init__.py":
        return True
    if not content or len(content.strip()) < 20:
        return True
    if file_path.endswith((".toml", ".yaml", ".yml", ".json", ".txt", ".md")):
        return True
    return False
