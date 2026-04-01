"""
pipeline/skills/skill_selector.py

Selects the right skills to inject into a codegen prompt based on:
  - The layer being generated (1-7)
  - Keywords in the agent spec (service_type, description, external_apis)
  - The specific file path being generated

Skills are injected as a "SKILL GUIDANCE" section in the codegen prompt.
This improves code quality by giving Claude methodology context for the
specific type of code it's generating.

SKILL CATEGORIES:
  Layer 1 (DB)       → systematic-debugging
  Layer 2 (Infra)    → owasp-security
  Layer 3 (API)      → owasp-security, systematic-debugging
  Layer 4 (Worker)   → multi-agent-patterns, context-engineering, memory-systems,
                        tool-design, context-fundamentals, context-optimization
  Layer 5 (Dashboard)→ ui-ux-pro-max, design-system, frontend-design, ui-styling
  Layer 6 (Deploy)   → (no skills — pure config files)
  Layer 7 (Docs)     → (no skills)

  Marketing agent    → marketing-psychology, copywriting, cold-email, social-content,
                        customer-research, email-sequence, launch-strategy
  SEO agent          → seo, seo-audit, seo-content, seo-technical, programmatic-seo
  Research agent     → deep-research, research-lookup, systematic-debugging
  Trading agent      → systematic-debugging, advanced-evaluation
  UI/UX agent        → ui-ux-pro-max, design-system, brand-guidelines, canvas-design
"""

from __future__ import annotations

from loguru import logger

from pipeline.skills.skill_library import get_skill_excerpt

# ── Layer → skill names ───────────────────────────────────────────────────────

LAYER_SKILLS: dict[int, list[str]] = {
    1: ["systematic-debugging"],
    2: ["owasp-security"],
    3: ["owasp-security", "systematic-debugging"],
    4: [
        "multi-agent-patterns",
        "context-fundamentals",
        "memory-systems",
        "tool-design",
        "context-optimization",
    ],
    5: ["ui-ux-pro-max", "design-system", "frontend-design", "ui-styling"],
    6: [],
    7: [],
}

# ── Keyword → skill names (matched against spec description + service_type) ───

KEYWORD_SKILLS: dict[str, list[str]] = {
    "marketing": [
        "marketing-psychology",
        "copywriting",
        "cold-email",
        "social-content",
        "customer-research",
        "email-sequence",
        "launch-strategy",
        "marketing-ideas",
    ],
    "seo": [
        "seo",
        "seo-audit",
        "seo-content",
        "seo-technical",
        "programmatic-seo",
        "seo-schema",
        "site-architecture",
    ],
    "email": ["cold-email", "email-sequence", "copywriting"],
    "lead": ["cold-email", "customer-research", "marketing-psychology", "sales-enablement"],
    "outreach": ["cold-email", "social-content", "copywriting", "customer-research"],
    "research": ["deep-research", "research-lookup", "systematic-debugging"],
    "trading": ["systematic-debugging", "advanced-evaluation"],
    "analytics": ["analytics-tracking", "statistical-analysis"],
    "content": ["copywriting", "social-content", "content-strategy", "copy-editing"],
    "design": ["ui-ux-pro-max", "design-system", "brand-guidelines", "canvas-design"],
    "brand": ["brand-guidelines", "brand", "ui-ux-pro-max"],
    "ads": ["paid-ads", "ad-creative", "marketing-psychology"],
    "referral": ["referral-program", "marketing-psychology"],
    "pricing": ["pricing-strategy", "marketing-psychology"],
    "competitor": ["competitor-alternatives", "seo-audit"],
    "cro": ["page-cro", "form-cro", "signup-flow-cro", "onboarding-cro"],
    "detailing": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "social-content",
    ],
    "construction": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "sales-enablement",
    ],
}

# Max skills to inject per prompt (keeps token cost reasonable)
MAX_SKILLS_PER_PROMPT = 3
MAX_CHARS_PER_SKILL = 1500


def select_skills(
    spec: dict,
    layer: int,
    file_path: str = "",
) -> list[tuple[str, str]]:
    """
    Select relevant skills for a codegen call.

    Returns list of (skill_name, skill_content) tuples — only skills that
    are actually installed and have content.

    Args:
        spec: The full agent spec dict
        layer: The layer number (1-7)
        file_path: The file path being generated (for fine-grained selection)
    """
    selected: list[str] = []
    seen: set[str] = set()

    def add(skill_name: str) -> None:
        if skill_name not in seen:
            seen.add(skill_name)
            selected.append(skill_name)

    # 1. Layer-based skills
    for skill in LAYER_SKILLS.get(layer, []):
        add(skill)

    # 2. Keyword-based skills from spec
    search_text = " ".join([
        spec.get("description", ""),
        spec.get("service_type", ""),
        spec.get("agent_name", ""),
        " ".join(spec.get("external_apis", [])),
    ]).lower()

    for keyword, skills in KEYWORD_SKILLS.items():
        if keyword in search_text:
            for skill in skills:
                add(skill)

    # 3. Fine-grained file path hints
    fp = file_path.lower()
    if "dashboard" in fp or ".tsx" in fp or ".jsx" in fp or "frontend" in fp:
        for s in ["ui-ux-pro-max", "design-system", "ui-styling"]:
            add(s)
    if "auth" in fp or "security" in fp or "middleware" in fp:
        add("owasp-security")
    if "test" in fp:
        add("tdd-guard")
    if "worker" in fp or "pipeline" in fp or "agent" in fp:
        for s in ["multi-agent-patterns", "tool-design"]:
            add(s)

    # 4. Cap at MAX_SKILLS_PER_PROMPT to keep token cost down
    top_skills = selected[:MAX_SKILLS_PER_PROMPT]

    # 5. Load actual content (skip skills that aren't installed)
    result: list[tuple[str, str]] = []
    for name in top_skills:
        content = get_skill_excerpt(name, max_chars=MAX_CHARS_PER_SKILL)
        if content:
            result.append((name, content))
        else:
            logger.debug(f"Skill '{name}' selected but not installed — skipping")

    if result:
        logger.debug(f"Injecting {len(result)} skills for layer {layer}: {[r[0] for r in result]}")

    return result


def build_skills_section(
    spec: dict,
    layer: int,
    file_path: str = "",
) -> str | None:
    """
    Build the skills injection block for a codegen prompt.
    Returns None if no relevant skills found.
    """
    skills = select_skills(spec, layer, file_path)
    if not skills:
        return None

    lines = ["SKILL GUIDANCE (apply these methodologies when generating this file):"]
    for name, content in skills:
        lines.append(f"\n--- {name.upper().replace('-', ' ')} ---")
        lines.append(content)

    return "\n".join(lines)
