"""
pipeline/skills/skill_library.py

Loads and indexes Claude skill files from ~/.claude/skills/.
Skills are methodology guides that get injected into Claude prompts
to improve code generation quality.

Skills are loaded lazily and cached — only read from disk once per process.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from loguru import logger

SKILLS_DIR = Path.home() / ".claude" / "skills"

# How many chars of a skill to include per injection (keeps token cost down)
MAX_SKILL_CHARS = 2000


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from skill content."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3 :].strip()
    return content.strip()


@lru_cache(maxsize=None)
def _load_all_skills() -> dict[str, str]:
    """
    Load all SKILL.md files from SKILLS_DIR.
    Returns dict of {skill_name: skill_content (frontmatter stripped)}.
    Cached after first call.
    """
    skills: dict[str, str] = {}
    if not SKILLS_DIR.exists():
        logger.warning(f"Skills directory not found: {SKILLS_DIR}")
        return skills

    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            raw = skill_file.read_text(encoding="utf-8", errors="ignore")
            content = _strip_frontmatter(raw)
            if content:
                skills[skill_dir.name] = content
        except Exception as exc:
            logger.debug(f"Could not load skill {skill_dir.name}: {exc}")

    logger.info(f"SkillLibrary loaded {len(skills)} skills from {SKILLS_DIR}")
    return skills


def get_skill(name: str) -> str | None:
    """Return full content of a named skill, or None if not found."""
    return _load_all_skills().get(name)


def get_skill_excerpt(name: str, max_chars: int = MAX_SKILL_CHARS) -> str | None:
    """Return up to max_chars of a skill's content."""
    content = get_skill(name)
    if content is None:
        return None
    if len(content) <= max_chars:
        return content
    # Truncate at a paragraph boundary if possible
    truncated = content[:max_chars]
    last_newline = truncated.rfind("\n\n")
    if last_newline > max_chars // 2:
        truncated = truncated[:last_newline]
    return truncated + "\n\n[...skill truncated for context efficiency]"


def list_available_skills() -> list[str]:
    """Return sorted list of all installed skill names."""
    return sorted(_load_all_skills().keys())


def reload_skills() -> None:
    """Force reload of skill cache (useful after installing new skills)."""
    _load_all_skills.cache_clear()
    _load_all_skills()
