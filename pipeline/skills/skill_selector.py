"""
pipeline/skills/skill_selector.py

Selects skills to inject into every codegen prompt. NO CAPS on skill count —
every relevant skill is included. Token budget managed via chars-per-skill.

THREE TIERS OF SKILL INJECTION:

  Tier 1 — FORGE UNIVERSAL (every layer, every agent, always):
    Skills that make The Forge itself smarter. Prompt engineering, reasoning,
    verification, conciseness, reflection. Always present.

  Tier 2 — LAYER SKILLS (specific to the layer being generated):
    Layer 1 (DB)        → debugging, root cause, TDD
    Layer 2 (Infra)     → security, planning, project structure
    Layer 3 (API)       → security, debugging, TDD, implementation patterns
    Layer 4 (Worker)    → ALL context/memory skills + ALL agent architecture
                          skills + evaluation + multi-agent orchestration
    Layer 5 (Dashboard) → ALL UI/UX skills + design system + frontend patterns
    Layer 6 (Deploy)    → security, verification
    Layer 7 (Docs)      → writing, documentation, markdown

  Tier 3 — DOMAIN SKILLS (matched from agent spec keywords):
    Stacked across all matching keywords. For DDD detailing agent Layer 4:
    marketing-psychology + copywriting + cold-email + customer-research +
    email-sequence + sales-enablement + social-content + referral-program
    + every other keyword match.

EMBED SECTION (Layer 4 only):
    Domain skills are also embedded into the generated agent's own Claude
    system prompts verbatim, so the running agent applies skill methodology
    to its own AI calls at runtime.

For a DDD lead gen agent, Layer 4 gets 40-50+ skills working together.
"""

from __future__ import annotations

from loguru import logger

from pipeline.skills.skill_library import get_skill_excerpt

# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: FORGE UNIVERSAL SKILLS
# Injected on every layer, every agent. These make The Forge itself smarter —
# better reasoning, better prompts, better verification, better output.
# ─────────────────────────────────────────────────────────────────────────────

FORGE_UNIVERSAL_SKILLS: list[str] = [
    # Prompt & Claude intelligence
    "prompt-engineering",            # The Forge writes system prompts — this is critical
    "apply-anthropic-skill-best-practices",  # Best practices for Claude usage
    "claude-api",                    # Claude API patterns and SDK usage
    "test-prompt",                   # Test and validate prompts before using
    # Reasoning & thinking
    "thought-based-reasoning",       # Chain-of-thought for every generation decision
    "tree-of-thoughts",              # Systematic exploration for complex files
    # Execution quality
    "verification-before-completion", # Never mark done without verifying
    "do-and-judge",                  # Generate then immediately self-verify
    "reflect",                       # Self-reflection on output before returning
    # Continuous improvement
    "kaizen",                        # Every file should be the best version possible
    "using-superpowers",             # Meta-skill: use all available skills effectively
    # Output quality
    "write-concisely",               # Clean, concise code and prompts
    # Debugging (universal — every layer can have issues)
    "systematic-debugging",          # Root cause before fixes, always
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: LAYER-SPECIFIC SKILLS
# ─────────────────────────────────────────────────────────────────────────────

LAYER_SKILLS: dict[int, list[str]] = {
    # ── Layer 1: Database Schema ──────────────────────────────────────────────
    1: [
        "systematic-debugging",
        "root-cause-tracing",
        "tdd-guard",
        "cause-and-effect",
        "why",
        "analyse-problem",
        "analyze-issue",
    ],

    # ── Layer 2: Infrastructure ───────────────────────────────────────────────
    2: [
        "owasp-security",
        "systematic-debugging",
        "root-cause-tracing",
        "planning-with-files",
        "project-development",
        "setup-code-formating",
        "cause-and-effect",
    ],

    # ── Layer 3: Backend API ──────────────────────────────────────────────────
    3: [
        "owasp-security",
        "systematic-debugging",
        "root-cause-tracing",
        "tdd-guard",
        "test-driven-development",
        "write-tests",
        "fix-tests",
        "implement",
        "do-in-steps",
        "executing-plans",
        "verification-before-completion",
        "cause-and-effect",
        "why",
        "analyze-issue",
        "add-typescript-best-practices",
        "query",                     # DB query patterns
        "database-lookup",           # Database lookup best practices
        "status",                    # Status endpoint patterns
        "requesting-code-review",    # Review before considering complete
        "review-local-changes",      # Review changes thoroughly
    ],

    # ── Layer 4: Worker / Agent Logic ─────────────────────────────────────────
    # Most critical layer — this is where the generated agent makes its own
    # Claude API calls. Every context, memory, orchestration, and evaluation
    # skill applies here.
    4: [
        # Context & memory (the foundation of every intelligent agent)
        "context-fundamentals",
        "context-engineering",
        "context-optimization",
        "context-compression",
        "context-degradation",
        "memory-systems",
        "filesystem-context",
        "decay",
        # Multi-agent orchestration
        "multi-agent-patterns",
        "dispatching-parallel-agents",
        "do-in-parallel",
        "subagent-driven-development",
        "launch-sub-agent",
        "hosted-agents",
        "create-agent",
        # Tool & agent design
        "tool-design",
        "mcp-builder",
        "bdi-mental-states",
        # Evaluation (the agent must evaluate its own outputs)
        "evaluation",
        "advanced-evaluation",
        "agent-evaluation",
        "critique",
        "judge",
        "judge-with-debate",
        "do-competitively",
        # Execution patterns
        "implement",
        "do-in-steps",
        "do-in-parallel",
        "executing-plans",
        "plan",
        "make-plan",
        # Reasoning (agents need deep reasoning)
        "cause-and-effect",
        "root-cause-tracing",
        "why",
        "what-if-oracle",
        "propose-hypotheses",
        "brainstorm",
        "brainstorming",
        "analyse",
        "plan-do-check-act",         # Iterative improvement loop
        "mem-search",                # Search memory for relevant patterns
        "memorize",                  # Curate insights into persistent memory
        "create-rule",               # Generate meta-rules from outcomes
        "review-pr",                 # Review generated code before committing
        "review-local-changes",      # Review all changes thoroughly
        "receiving-code-review",     # Apply review feedback correctly
        "requesting-code-review",    # Request review before completing
        "parallel-web",              # Parallel web search patterns
        "get-available-resources",   # Discover available tools/resources
        "writing-plans",             # Write comprehensive implementation plans
        "add-task",                  # Task management in agent workflows
        "load-issues",               # Load and process issue queues
    ],

    # ── Layer 5: Web Dashboard ────────────────────────────────────────────────
    5: [
        # UI/UX core
        "ui-ux-pro-max",
        "design-system",
        "frontend-design",
        "ui-styling",
        "design",
        # Extended UI
        "web-artifacts-builder",
        "theme-factory",
        "canvas-design",
        "brand-guidelines",
        # TypeScript & testing
        "add-typescript-best-practices",
        "webapp-testing",
        "tdd-guard",
        "write-tests",
        # Implementation
        "implement",
        "do-in-steps",
        "verification-before-completion",
        "cause-and-effect",
    ],

    # ── Layer 6: Deployment ───────────────────────────────────────────────────
    6: [
        "owasp-security",
        "systematic-debugging",
        "verification-before-completion",
        "cause-and-effect",
        "commit",                    # Proper git commit conventions
        "create-pr",                 # PR creation patterns
        "finishing-a-development-branch",  # Branch completion checklist
        "using-git-worktrees",       # Worktree management
        "attach-review-to-pr",       # Attach reviews to PRs
    ],

    # ── Layer 7: Documentation ────────────────────────────────────────────────
    7: [
        "write-concisely",
        "writing-skills",
        "markdown-mermaid-writing",
        "doc-coauthoring",
        "update-docs",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: DOMAIN SKILLS
# All matching keywords are checked and stacked — no cap.
# For a detailing + lead + outreach agent, ALL three keyword lists apply.
# ─────────────────────────────────────────────────────────────────────────────

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
        "product-marketing-context",
    ],
    "lead": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "sales-enablement",
        "copywriting",
        "email-sequence",
        "social-content",
        "lead-magnets",
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
        "seo-page",
        "seo-sitemap",
        "seo-backlinks",
        "ai-seo",
        "seo-plan",
        "seo-competitor-pages",
        "seo-geo",
        "seo-hreflang",
        "seo-image-gen",
        "seo-images",
        "seo-maps",
        "seo-programmatic",
    ],
    "research": [
        "deep-research",
        "research-lookup",
        "systematic-debugging",
        "market-research-reports",
        "competitor-alternatives",
        "smart-explore",
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
        "exploratory-data-analysis",
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
        "evaluation",
        "cause-and-effect",
        "what-if-oracle",
    ],
    "design": [
        "ui-ux-pro-max",
        "design-system",
        "brand-guidelines",
        "canvas-design",
        "ui-styling",
        "design",
    ],
    "brand": [
        "brand-guidelines",
        "brand",
        "ui-ux-pro-max",
        "design",
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
        "churn-prevention",
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
        "onboarding-cro",
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
        "dispatching-parallel-agents",
    ],
    "intelligence": [
        "deep-research",
        "advanced-evaluation",
        "evaluation",
        "memory-systems",
        "context-engineering",
    ],
    "finance": [
        "statistical-analysis",
        "advanced-evaluation",
        "what-if-oracle",
    ],
    "social": [
        "social-content",
        "copywriting",
        "marketing-psychology",
        "content-strategy",
    ],
    "revenue": [
        "revops",
        "pricing-strategy",
        "churn-prevention",
        "sales-enablement",
        "marketing-psychology",
    ],
    "report": [
        "pptx",
        "slides",
        "pdf",
        "xlsx",
        "markdown-mermaid-writing",
        "timeline-report",
        "write-concisely",
    ],
    "presentation": [
        "pptx",
        "slides",
        "design-system",
        "write-concisely",
    ],
    "data": [
        "xlsx",
        "pdf",
        "database-lookup",
        "query",
        "markdown-mermaid-writing",
    ],
    "free tool": [
        "free-tool-strategy",
        "marketing-psychology",
        "lead-magnets",
    ],
    "property management": [
        "cold-email",
        "customer-research",
        "marketing-psychology",
        "sales-enablement",
        "revops",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# TOKEN BUDGET
# No count cap. Chars-per-skill controls total size.
# ─────────────────────────────────────────────────────────────────────────────

# Chars per skill in the GUIDANCE section (used during The Forge's generation)
GUIDANCE_CHARS_PER_SKILL = 1200

# Chars per skill in the EMBED section (pasted into generated agent's system prompts)
EMBED_CHARS_PER_SKILL = 2500

# Layers where domain skills get embedded into generated agent system prompts
EMBED_SKILLS_LAYERS = {4}


# ─────────────────────────────────────────────────────────────────────────────
# FILE PATH HINTS
# ─────────────────────────────────────────────────────────────────────────────

def _path_skills(file_path: str) -> list[str]:
    """Extra skills based on the specific file path being generated."""
    fp = file_path.lower()
    extras: list[str] = []
    if any(x in fp for x in ["dashboard", ".tsx", ".jsx", "frontend", "component"]):
        extras += ["ui-ux-pro-max", "design-system", "ui-styling", "add-typescript-best-practices"]
    if any(x in fp for x in ["auth", "security", "middleware", "permission"]):
        extras += ["owasp-security"]
    if any(x in fp for x in ["test", "spec", "e2e"]):
        extras += ["tdd-guard", "test-driven-development", "write-tests"]
    if any(x in fp for x in ["worker", "pipeline", "orchestrat"]):
        extras += ["multi-agent-patterns", "tool-design", "dispatching-parallel-agents"]
    if any(x in fp for x in ["email", "sms", "message", "notification", "alert"]):
        extras += ["cold-email", "copywriting", "marketing-psychology"]
    if any(x in fp for x in ["lead", "prospect", "contact", "outreach"]):
        extras += ["cold-email", "customer-research", "sales-enablement", "marketing-psychology"]
    if any(x in fp for x in ["review", "reputation", "rating", "feedback"]):
        extras += ["marketing-psychology", "social-content", "copywriting"]
    if any(x in fp for x in ["referral", "neighbour", "neighbor", "suburb"]):
        extras += ["referral-program", "marketing-psychology"]
    if any(x in fp for x in ["campaign", "broadcast", "blast"]):
        extras += ["marketing-psychology", "copywriting", "cold-email"]
    if any(x in fp for x in ["knowledge", "memory", "embed", "vector", "retriev"]):
        extras += ["memory-systems", "context-engineering", "context-optimization"]
    if any(x in fp for x in ["evaluat", "score", "quality", "judge"]):
        extras += ["evaluation", "advanced-evaluation", "judge-with-debate"]
    if any(x in fp for x in ["prompt", "system_prompt", "system prompt"]):
        extras += ["prompt-engineering", "apply-anthropic-skill-best-practices"]
    if any(x in fp for x in ["deploy", "fly.toml", "dockerfile", "github/workflows"]):
        extras += ["owasp-security", "verification-before-completion"]
    return extras


# ─────────────────────────────────────────────────────────────────────────────
# CORE SELECTION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def select_skills(
    spec: dict,
    layer: int,
    file_path: str = "",
) -> list[tuple[str, str]]:
    """
    Select ALL relevant skills for a codegen prompt. No count cap.

    Order: Universal → Layer → Domain (keyword-matched) → Path hints
    Returns list of (skill_name, skill_content) — only installed skills.
    """
    selected: list[str] = []
    seen: set[str] = set()

    def add(skill_name: str) -> None:
        if skill_name not in seen:
            seen.add(skill_name)
            selected.append(skill_name)

    # Tier 1: Universal (always)
    for skill in FORGE_UNIVERSAL_SKILLS:
        add(skill)

    # Tier 2: Layer skills
    for skill in LAYER_SKILLS.get(layer, []):
        add(skill)

    # Tier 3: Domain skills — ALL matching keywords stacked
    search_text = " ".join([
        spec.get("description", ""),
        spec.get("service_type", ""),
        spec.get("agent_name", ""),
        spec.get("business_name", ""),
        " ".join(spec.get("external_apis", [])),
    ]).lower()

    for keyword, skills in KEYWORD_SKILLS.items():
        if keyword in search_text:
            for skill in skills:
                add(skill)

    # Path-level hints
    for skill in _path_skills(file_path):
        add(skill)

    # Load content — skip any not installed
    result: list[tuple[str, str]] = []
    for name in selected:
        content = get_skill_excerpt(name, max_chars=GUIDANCE_CHARS_PER_SKILL)
        if content:
            result.append((name, content))
        else:
            logger.debug(f"Skill '{name}' not installed — skipping")

    logger.info(
        f"Layer {layer} | {file_path or 'unknown'} | "
        f"{len(result)} skills injected: {[r[0] for r in result]}"
    )
    return result


def _select_embed_skills(spec: dict) -> list[tuple[str, str]]:
    """
    Select domain skills to embed verbatim into the generated agent's own
    Claude system prompts. No cap — all matching domain skills included.
    Longer excerpts (EMBED_CHARS_PER_SKILL) so the agent gets full methodology.
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
    for name in selected:
        content = get_skill_excerpt(name, max_chars=EMBED_CHARS_PER_SKILL)
        if content:
            result.append((name, content))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT SECTION BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_skills_section(
    spec: dict,
    layer: int,
    file_path: str = "",
) -> str | None:
    """
    Build the complete skills injection block for a codegen prompt.

    Returns None if no skills found.

    Structure:
      SKILL GUIDANCE — N skills (Universal + Layer + Domain + Path)
        [all skill content blocks]

      EMBED THESE SKILLS IN GENERATED SYSTEM PROMPTS (Layer 4 only)
        [domain skill content to paste into agent's own Claude calls]
    """
    skills = select_skills(spec, layer, file_path)
    if not skills:
        return None

    lines = [
        f"SKILL GUIDANCE — {len(skills)} skills active for this file "
        f"(Universal + Layer {layer} + Domain + Path). "
        f"Apply all methodologies when generating:"
    ]
    for name, content in skills:
        lines.append(f"\n--- {name.upper().replace('-', ' ')} ---")
        lines.append(content)

    # Layer 4: embed domain skills into the generated agent's system prompts
    if layer in EMBED_SKILLS_LAYERS:
        embed_skills = _select_embed_skills(spec)
        if embed_skills:
            lines.append(
                f"\n\nEMBED THESE {len(embed_skills)} DOMAIN SKILLS IN GENERATED SYSTEM PROMPTS:"
            )
            lines.append(
                "The system prompt strings you write into this agent's Claude API calls "
                "MUST incorporate the following skill methodology. This is mandatory — "
                "extract and embed the key principles directly into the system prompt "
                "constants in the generated code so the running agent applies expert "
                "methodology to every AI call it makes at runtime, not just during generation:"
            )
            for name, content in embed_skills:
                lines.append(
                    f"\n=== {name.upper().replace('-', ' ')} "
                    f"(embed in generated system prompt) ==="
                )
                lines.append(content)

    return "\n".join(lines)
