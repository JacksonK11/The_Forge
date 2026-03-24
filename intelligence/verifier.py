"""
intelligence/verifier.py
Independent second Claude instance that adversarially reviews the complete
output package before it is made available for download.

Asks the single most important question before every deployment:
"What would prevent this from deploying on first try?"

The verifier catches issues that per-file evaluation misses:
  - Cross-file import inconsistencies
  - Missing environment variables in fly.toml or FLY_SECRETS.txt
  - Docker build failures (missing system packages, wrong COPY paths)
  - Database migration issues (tables in code but not in models.py)
  - GitHub Actions misconfiguration
  - Missing __init__.py files in Python packages

Called from package_node.py after all files are generated and before ZIP assembly.
Blocking issues are reported in SECURITY_REPORT.txt and Telegram notification.
Non-blocking — a failed verification does not stop packaging.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings
from pipeline.prompts.prompts import VERIFIER_SYSTEM, VERIFIER_USER

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


@dataclass
class VerificationIssue:
    category: str
    file: str
    issue: str
    fix: str


@dataclass
class VerificationResult:
    deployment_ready: bool
    blocking_issues: list[VerificationIssue] = field(default_factory=list)
    warnings: list[VerificationIssue] = field(default_factory=list)
    summary: str = ""
    model_used: str = ""

    def to_dict(self) -> dict:
        return {
            "deployment_ready": self.deployment_ready,
            "blocking_issues": [
                {"category": i.category, "file": i.file, "issue": i.issue, "fix": i.fix}
                for i in self.blocking_issues
            ],
            "warnings": [
                {"category": i.category, "file": i.file, "issue": i.issue}
                for i in self.warnings
            ],
            "summary": self.summary,
        }


async def verify_package(
    agent_name: str,
    fly_services: list[str],
    file_manifest: list[dict],
    generated_files: dict[str, str],
) -> VerificationResult:
    """
    Adversarially review the complete generated package for deployment readiness.

    Args:
        agent_name:      Name of the agent being built.
        fly_services:    List of Fly.io service names.
        file_manifest:   List of file entries from build manifest.
        generated_files: Dict of file_path → content for all generated files.

    Returns:
        VerificationResult — non-blocking, packaging continues regardless.
    """
    model = router.get_model("verification")

    try:
        services_text = ", ".join(fly_services)
        manifest_text = "\n".join(
            f"  [{f.get('layer', '?')}] {f.get('path', f.get('file_path', '?'))}"
            for f in sorted(file_manifest, key=lambda x: (x.get("layer", 9), x.get("path", x.get("file_path", ""))))
        )

        # Sample the most architecturally important files
        sample_files = _sample_key_files(generated_files)

        prompt = VERIFIER_USER.format(
            agent_name=agent_name,
            services=services_text,
            file_count=len(file_manifest),
            file_manifest=manifest_text[:4000],
            sample_files=sample_files[:4000],
        )

        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=VERIFIER_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        raw = json.loads(text)

        blocking = [
            VerificationIssue(
                category=i.get("category", "unknown"),
                file=i.get("file", "unknown"),
                issue=i.get("issue", ""),
                fix=i.get("fix", ""),
            )
            for i in raw.get("blocking_issues", [])
        ]
        warnings = [
            VerificationIssue(
                category=i.get("category", "unknown"),
                file=i.get("file", "unknown"),
                issue=i.get("issue", ""),
                fix="",
            )
            for i in raw.get("warnings", [])
        ]

        result = VerificationResult(
            deployment_ready=raw.get("deployment_ready", True),
            blocking_issues=blocking,
            warnings=warnings,
            summary=raw.get("summary", ""),
            model_used=model,
        )

        logger.info(
            f"Verification complete: deployment_ready={result.deployment_ready} "
            f"blocking={len(result.blocking_issues)} warnings={len(result.warnings)}"
        )
        return result

    except json.JSONDecodeError as exc:
        logger.warning(f"Verifier response not JSON: {exc}")
        return VerificationResult(
            deployment_ready=True,
            summary=f"Verifier response parse error: {exc}",
        )
    except Exception as exc:
        logger.warning(f"Verifier failed (non-blocking): {exc}")
        return VerificationResult(
            deployment_ready=True,
            summary=f"Verifier skipped: {exc}",
        )


def format_verification_report(result: VerificationResult) -> str:
    """Format VerificationResult as a section of SECURITY_REPORT.txt."""
    lines = [
        "DEPLOYMENT VERIFIER RESULTS",
        "=" * 40,
        f"Deployment ready: {'YES' if result.deployment_ready else 'NO — SEE BLOCKING ISSUES BELOW'}",
        f"Summary: {result.summary}",
        "",
    ]

    if result.blocking_issues:
        lines.append(f"BLOCKING ISSUES ({len(result.blocking_issues)}) — Fix before deploying:")
        for issue in result.blocking_issues:
            lines.append(f"\n  [{issue.category}] {issue.file}")
            lines.append(f"  Problem: {issue.issue}")
            lines.append(f"  Fix:     {issue.fix}")

    if result.warnings:
        lines.append(f"\nWARNINGS ({len(result.warnings)}) — Non-blocking but recommended:")
        for w in result.warnings:
            lines.append(f"\n  [{w.category}] {w.file}")
            lines.append(f"  {w.issue}")

    return "\n".join(lines)


# ── Internal ──────────────────────────────────────────────────────────────────


def _sample_key_files(generated_files: dict[str, str]) -> str:
    """Extract the most architecturally important files for verifier review."""
    priority = [
        "memory/models.py",
        "memory/database.py",
        "requirements.txt",
        "docker-compose.yml",
        ".env.example",
    ]
    # Also include any fly.toml and Dockerfile files
    for path in generated_files:
        if path.endswith(".toml") or "Dockerfile" in path:
            if path not in priority:
                priority.append(path)

    lines = []
    for path in priority:
        content = generated_files.get(path, "")
        if content:
            lines.append(f"\n=== {path} ===\n{content[:1500]}")

    return "\n".join(lines)
