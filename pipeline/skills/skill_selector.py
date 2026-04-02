"""
pipeline/skills/skill_selector.py

Selects the right skills to inject into a codegen prompt based on:
  - The layer being generated (1-7)
  - Keywords in the agent spec (service_type, description, external_apis)
  - The specific file path being generated

Skills are NOT arbitrarily capped — every relevant skill is included.
A DDD lead gen agent generating Layer 4 (worker) code will get ALL of:
  marketing-psychology, copywriting, cold-email, customer-research,
  email-sequence, sales-enablement, social-content, multi-agent-patterns,
  tool-design, context-fundamentals, memory-systems... and more.

Token budget is managed by char limits per skill, not by cutting skills out.

LAYER SKILL SETS:
  Layer 1 (DB)        → systematic-debugging, tdd-guard
  Layer 2 (Infra)     → owasp-security, systematic-debugging
  Layer 3 (API)       → owasp-security, systematic-debugging, tdd-guard
  Layer 4 (Worker)    → multi-agent-patterns, context-fundamentals,
                         memory-systems, tool-design, context-optimization,
                         dispatching-parallel-agents, context-compression
                         + ALL domain skills matching the agent's purpose
  Layer 5 (Dashboard) → ui-ux-pro-max, design-system, frontend-design,
                         ui-styling, brand-guidelines, canvas-design
                         + domain UI skills (e.g. brand for brand agents)
  Layer 6 (Deploy)    → (no skills — pure config files)
  Layer 7 (Docs)      → (no skills)

DOMAIN SKILL SETS (stacked — all matching keywords apply):
  marketing    → marketing-psychology, copywriting, cold-email, social-content,
                 customer-research, email-sequence, launch-strategy,
                 marketing-ideas, content-strategy, copy-editing
  lead/outreach→ cold-email, customer-research, marketing-psychology,
                 sales-enablement, copywriting, email-sequence, social-content
  seo          → seo, seo-audit, seo-content, seo-technical, programmatic-seo,
                 seo-schema, seo-local, site-architecture, seo-google
  research     → deep-research, research-lookup, systematic-debugging,
                 market-research-reports, competitor-alternatives
  ads          → paid-ads, ad-creative, marketing-psychology, copywriting
  cro          → page-cro, form-cro, signup-flow-cro, onboarding-cro,
                 paywall-upgrade-cro, popup-cro
  analytics    → analytics-tracking, statistical-analysis, ab-test-setup
  referral     → referral-program, marketing-psychology, copywriting
  pricing      → pricing-strategy, marketing-psychology
  competitor   → competitor-alternatives, seo-audit, market-research-reports
  content      → copywriting, social-content, content-strategy, copy-editing
  trading      → systematic-debugging, advanced-evaluation, statistical-analysis
  design/brand → ui-ux-pro-max, design-system, brand-guidelines, brand,
                 canvas-design, ui-styling
  detailing    → cold-email, customer-research, marketing-psychology,
                 social-content, email-sequence, sales-enablement, copywriting,
                 referral-program
  construction → cold-email, customer-research, marketing-psychology,
                 sales-enablement, copywriting, email-sequence
  booking      → customer-research, marketing-psychology, email-sequence
  review/reputation → marketing-psychology, social-content, copywriting
"""

from __future__ import annotations

from loguru import logger

from pipeline.skills.skill_library import get_skill_excerpt

# ── Layer → skill names ───────────────────────────────────────────────────────

LAYER_SKILLS: dict[int, list[str]] = {
    1: [
        "systematic-debugging",
        "tdd-guard",
    ],
    2: [
        "owasp-security",
        "systematic-debugging",
    ],
    3: [
        "owasp-security",
        "systematic-debugging",
        "tdd-guard",
    ],
    4: [
        "multi-agent-patterns",
        "context-fundamentals",
        "memory-systems",
        "tool-design",
        "context-optimization",
        "dispatching-parallel-agents",
        "context-compression",
    ],
    5: [
        "ui-ux-pro-max",
        "design-system",
        "frontend-design",
        "ui-styling",
        "brand-guidelines",
        "canvas-design",
    ],
    6: [],
    7: [],
}

# ── Keyword → skill names (ALL keywords are checked, ALL matches are stacked) ─
# Order within each list = priority (first = most important)

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
        "content-strategy",
        "copy-editing",
    ],
    "lead": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "sales-enablement",
        "copywriting",
        "email-sequence",
        "social-content",
    ],
    "outreach": [
        "cold-email",
        "social-content",
        "copywriting",
        "customer-research",
        "email-sequence",
        "sales-enablement",
        "marketing-psychology",
    ],
    "seo": [
        "seo",
        "seo-audit",
        "seo-content",
        "seo-technical",
        "programmatic-seo",
        "seo-schema",
        "seo-local",
        "site-architecture",
        "seo-google",
    ],
    "research": [
        "deep-research",
        "research-lookup",
        "systematic-debugging",
        "market-research-reports",
        "competitor-alternatives",
    ],
    "email": [
        "cold-email",
        "email-sequence",
        "copywriting",
        "marketing-psychology",
    ],
    "ads": [
        "paid-ads",
        "ad-creative",
        "marketing-psychology",
        "copywriting",
    ],
    "cro": [
        "page-cro",
        "form-cro",
        "signup-flow-cro",
        "onboarding-cro",
        "paywall-upgrade-cro",
        "popup-cro",
    ],
    "analytics": [
        "analytics-tracking",
        "statistical-analysis",
        "ab-test-setup",
    ],
    "referral": [
        "referral-program",
        "marketing-psychology",
        "copywriting",
    ],
    "pricing": [
        "pricing-strategy",
        "marketing-psychology",
    ],
    "competitor": [
        "competitor-alternatives",
        "seo-audit",
        "market-research-reports",
    ],
    "content": [
        "copywriting",
        "social-content",
        "content-strategy",
        "copy-editing",
    ],
    "trading": [
        "systematic-debugging",
        "advanced-evaluation",
        "statistical-analysis",
    ],
    "design": [
        "ui-ux-pro-max",
        "design-system",
        "brand-guidelines",
        "canvas-design",
        "ui-styling",
    ],
    "brand": [
        "brand-guidelines",
        "brand",
        "ui-ux-pro-max",
    ],
    "detailing": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "social-content",
        "email-sequence",
        "sales-enablement",
        "copywriting",
        "referral-program",
    ],
    "construction": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "sales-enablement",
        "copywriting",
        "email-sequence",
    ],
    "booking": [
        "customer-research",
        "marketing-psychology",
        "email-sequence",
    ],
    "review": [
        "marketing-psychology",
        "social-content",
        "copywriting",
    ],
    "reputation": [
        "marketing-psychology",
        "social-content",
        "copywriting",
    ],
    "property": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "sales-enablement",
    ],
    "real estate": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "sales-enablement",
    ],
    "automation": [
        "multi-agent-patterns",
        "tool-design",
        "context-fundamentals",
    ],
}

# ── Token budget ──────────────────────────────────────────────────────────────
# No cap on skill COUNT — include all relevant skills.
# Budget is managed via chars-per-skill (shorter excerpts = more skills fit).
# Total injection budget: ~12,000 chars for guidance + ~6,000 chars for embed.

# Guidance section: how many chars per skill excerpt (used during generation)
GUIDANCE_CHARS_PER_SKILL = 1200

# Embed section: chars per skill pasted into generated system prompts
EMBED_CHARS_PER_SKILL = 2500

# Max domain skills to embed into agent system prompts (quality > quantity here)
MAX_EMBED_SKILLS = 4

# Layer 4 (Worker/Agent logic) = where generated agents make their own Claude calls
EMBED_SKILLS_LAYERS = {4}


# ── File path → extra skills ──────────────────────────────────────────────────

def _path_skills(file_path: str) -> list[str]:
    """Return extra skills based on the file path being generated."""
    fp = file_path.lower()
    extras: list[str] = []
    if any(x in fp for x in ["dashboard", ".tsx", ".jsx", "frontend"]):
        extras += ["ui-ux-pro-max", "design-system", "ui-styling"]
    if any(x in fp for x in ["auth", "security", "middleware"]):
        extras += ["owasp-security"]
    if "test" in fp:
        extras += ["tdd-guard"]
    if any(x in fp for x in ["worker", "pipeline", "outreach", "campaign"]):
        extras += ["multi-agent-patterns", "tool-design"]
    if any(x in fp for x in ["email", "sms", "message", "notification"]):
        extras += ["cold-email", "copywriting", "marketing-psychology"]
    if any(x in fp for x in ["lead", "prospect", "contact"]):
        extras += ["cold-email", "customer-research", "sales-enablement"]
    if any(x in fp for x in ["review", "reputation", "rating"]):
        extras += ["marketing-psychology", "social-content"]
    if any(x in fp for x in ["referral", "neighbour", "neighbor"]):
        extras += ["referral-program", "marketing-psychology"]
    return extras


def select_skills(
    spec: dict,
    layer: int,
    file_path: str = "",
) -> list[tuple[str, str]]:
    """
    Select ALL relevant skills for a codegen call.

    No arbitrary count cap — every skill that matches is included.
    Token cost is managed via chars-per-skill, not by cutting skills.

    Returns list of (skill_name, skill_content) tuples — only installed skills.
    """
    selected: list[str] = []
    seen: set[str] = set()

    def add(skill_name: str) -> None:
        if skill_name not in seen:
            seen.add(skill_name)
            selected.append(skill_name)

    # 1. Layer baseline skills
    for skill in LAYER_SKILLS.get(layer, []):
        add(skill)

    # 2. ALL matching keyword skills from spec (every keyword checked)
    search_text = " ".join([
        spec.get("description", ""),
        spec.get("service_type", ""),
        spec.get("agent_name", ""),
        " ".join(spec.get("external_apis", [])),
        spec.get("business_name", ""),
    ]).lower()

    for keyword, skills in KEYWORD_SKILLS.items():
        if keyword in search_text:
            for skill in skills:
                add(skill)

    # 3. File path hints
    for skill in _path_skills(file_path):
        add(skill)

    # 4. Load all selected skills (skip missing ones)
    result: list[tuple[str, str]] = []
    for name in selected:
        content = get_skill_excerpt(name, max_chars=GUIDANCE_CHARS_PER_SKILL)
        if content:
            result.append((name, content))
        else:
            logger.debug(f"Skill '{name}' not installed — skipping")

    if result:
        logger.info(
            f"Layer {layer} | {file_path or 'unknown'} | "
            f"injecting {len(result)} skills: {[r[0] for r in result]}"
        )

    return result


def _select_domain_skills_for_embed(spec: dict) -> list[tuple[str, str]]:
    """
    Select domain skills to embed into the generated agent's own Claude
    system prompts. These make the *running agent* smarter — not The Forge.

    Returns up to MAX_EMBED_SKILLS with longer excerpts (EMBED_CHARS_PER_SKILL).
    """
    search_text = " ".join([
        spec.get("description", ""),
        spec.get("service_type", ""),
        spec.get("agent_name", ""),
        spec.get("business_name", ""),
    ]).lower()

    selected: list[str] = []
    seen: set[str] = set()

    def add(skill_name: str) -> None:
        if skill_name not in seen:
            seen.add(skill_name)
            selected.append(skill_name)

    for keyword, skills in KEYWORD_SKILLS.items():
        if keyword in search_text:
            for skill in skills:
                add(skill)

    result: list[tuple[str, str]] = []
    for name in selected[:MAX_EMBED_SKILLS]:
        content = get_skill_excerpt(name, max_chars=EMBED_CHARS_PER_SKILL)
        if content:
            result.append((name, content))

    return result


def build_skills_section(
    spec: dict,
    layer: int,
    file_path: str = "",
) -> str | None:
    """
    Build the complete skills injection block for a codegen prompt.

    ALL relevant skills are included — no arbitrary cap.
    For Layer 4 (Worker/Agent logic): also adds an EMBED section with
    domain skill content to paste verbatim into the generated agent's
    own Claude API system prompts.

    Returns None if no relevant skills found.
    """
    skills = select_skills(spec, layer, file_path)
    if not skills:
        return None

    lines = [
        f"SKILL GUIDANCE — {len(skills)} skills selected for this file "
        f"(apply all methodologies when generating):"
    ]
    for name, content in skills:
        lines.append(f"\n--- {name.upper().replace('-', ' ')} ---")
        lines.append(content)

    # Layer 4: also embed domain skills into generated agent system prompts
    if layer in EMBED_SKILLS_LAYERS:
        domain_skills = _select_domain_skills_for_embed(spec)
        if domain_skills:
            lines.append(
                f"\n\nEMBED THESE {len(domain_skills)} SKILLS IN GENERATED SYSTEM PROMPTS:"
            )
            lines.append(
                "The system prompt strings you write into this agent's Claude API calls "
                "MUST include the following skill methodology content. This is mandatory — "
                "paste the key principles directly into the system prompt constants in the "
                "generated code so the running agent applies expert methodology to every "
                "AI call it makes at runtime:"
            )
            for name, content in domain_skills:
                lines.append(
                    f"\n=== {name.upper().replace('-', ' ')} "
                    f"(embed in generated system prompt) ==="
                )
                lines.append(content)

    return "\n".join(lines)
