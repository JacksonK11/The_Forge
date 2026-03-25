"""
pipeline/services/dependency_manifest.py
Cross-file validation between layers.

After each layer completes, builds a manifest of exact names, paths, and exports
that downstream layers must use. Prevents import mismatches by giving every
subsequent file generation a concrete reference of what already exists.

Claude call (Haiku) extracts exports from completed files.
Regex fallback fires automatically if the Claude call fails — zero extra cost.
validate_file() is pure regex — runs on every file at zero cost.
"""

import json
import re

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings

_async_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# Regex patterns for fallback export extraction
_CLASS_RE = re.compile(r"^class\s+(\w+)", re.MULTILINE)
_FUNC_RE = re.compile(r"^(?:async\s+)?def\s+(\w+)", re.MULTILINE)
_CONST_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE)
_MODEL_RE = re.compile(r"__tablename__\s*=\s*['\"](\w+)['\"]", re.MULTILINE)
_ROUTE_RE = re.compile(r"""@\w+\.(?:get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""", re.MULTILINE)


class DependencyManifest:
    """
    Builds and maintains a cross-layer manifest of exported names.
    All methods are safe — failures log warnings and return empty/default structures.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    async def build_manifest(
        self,
        layer_num: int,
        completed_files: dict[str, str],
    ) -> dict:
        """
        Extract all importable names from files completed in this layer.

        Tries Claude (Haiku) first for accurate structured extraction.
        Falls back to regex scanning if Claude fails — always returns something.

        Returns: {"files": [{"path": "...", "exports": {...}}]}
        """
        if not completed_files:
            return {"layer": layer_num, "files": []}

        try:
            return await self._claude_extract(layer_num, completed_files)
        except Exception as exc:
            logger.warning(
                f"DependencyManifest Claude extraction failed for layer {layer_num} "
                f"(falling back to regex): {exc}"
            )
            return self._regex_extract(layer_num, completed_files)

    def format_for_prompt(self, manifest: dict) -> str:
        """
        Format the cumulative manifest into a clean reference block for prompt injection.
        This string is prepended to every file generation call for subsequent layers.
        """
        if not manifest.get("files"):
            return ""

        lines = ["DEPENDENCY MANIFEST — USE THESE EXACT NAMES AND PATHS"]
        for file_entry in manifest["files"]:
            path = file_entry.get("path", "")
            exports = file_entry.get("exports", {})
            parts: list[str] = []
            if exports.get("classes"):
                parts.append(f"classes [{', '.join(exports['classes'][:10])}]")
            if exports.get("functions"):
                parts.append(f"functions [{', '.join(exports['functions'][:10])}]")
            if exports.get("constants"):
                parts.append(f"constants [{', '.join(exports['constants'][:8])}]")
            if exports.get("models"):
                parts.append(f"models/tables [{', '.join(exports['models'][:8])}]")
            if exports.get("routes"):
                parts.append(f"routes [{', '.join(exports['routes'][:8])}]")
            if parts:
                lines.append(f"From {path}: {', '.join(parts)}")

        return "\n".join(lines)

    async def validate_file(
        self,
        file_content: str,
        file_spec: dict,
        manifest: dict,
    ) -> dict:
        """
        Fast regex check: scan imports in file_content against the manifest.
        Returns {'valid': bool, 'mismatches': [{'import': '...', 'suggestion': '...'}]}
        Zero Claude calls — runs on every generated file.
        """
        if not manifest.get("files") or not file_content:
            return {"valid": True, "mismatches": []}

        # Build lookup: exported name → source file
        name_to_source: dict[str, str] = {}
        for file_entry in manifest["files"]:
            source_path = file_entry.get("path", "")
            exports = file_entry.get("exports", {})
            for category in ("classes", "functions", "constants", "models"):
                for name in exports.get(category, []):
                    name_to_source[name] = source_path

        # Parse import statements from the file content
        import_pattern = re.compile(
            r"^from\s+([\w.]+)\s+import\s+(.+)$", re.MULTILINE
        )
        mismatches: list[dict] = []

        for match in import_pattern.finditer(file_content):
            names_str = re.sub(r"\(|\)", "", match.group(2))
            names = [
                n.strip().split(" as ")[0].strip()
                for n in names_str.split(",")
            ]
            for name in names:
                if not name or name == "*":
                    continue
                # Only flag if we know it SHOULD exist but it's not in the manifest
                # (avoid false positives for stdlib/third-party imports)
                if name in name_to_source:
                    continue  # Found in manifest — good
                # Check if any manifest file has a similar name (typo detection)
                similar = _find_similar_name(name, name_to_source)
                if similar:
                    mismatches.append({
                        "import": name,
                        "suggestion": f"Did you mean '{similar}' from '{name_to_source[similar]}'?",
                    })

        return {"valid": len(mismatches) == 0, "mismatches": mismatches}

    def accumulate(self, existing_manifest: dict, new_layer_manifest: dict) -> dict:
        """
        Merge a new layer's manifest into the cumulative manifest.
        Downstream layers see ALL prior layers' exports.
        """
        existing_files = existing_manifest.get("files", [])
        new_files = new_layer_manifest.get("files", [])

        # De-duplicate by path (new layer wins on conflict)
        path_to_entry: dict[str, dict] = {e["path"]: e for e in existing_files}
        for entry in new_files:
            path_to_entry[entry["path"]] = entry

        return {"files": list(path_to_entry.values())}

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _claude_extract(
        self, layer_num: int, completed_files: dict[str, str]
    ) -> dict:
        """Use Haiku to extract exports from completed files."""
        # Truncate each file to keep prompt manageable
        file_snippets = "\n\n".join(
            f"=== FILE: {path} ===\n{content[:1200]}"
            for path, content in list(completed_files.items())[:15]
        )

        prompt = (
            f"Extract all importable names from these Python files (layer {layer_num}).\n\n"
            f"{file_snippets}\n\n"
            f"For each file, list: exact file path, all class names, all async/sync function names "
            f"defined at module level, all exported constants (UPPER_CASE), "
            f"all SQLAlchemy model table names, all FastAPI route paths.\n\n"
            f"Return JSON only:\n"
            f'{{"files": [{{"path": "...", "exports": {{"classes": [], "functions": [], '
            f'"constants": [], "models": [], "routes": []}}}}]}}'
        )

        model = router.get_model("evaluation")
        response = await _async_client.messages.create(
            model=model,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        raw = json.loads(text)
        raw["layer"] = layer_num
        return raw

    def _regex_extract(
        self, layer_num: int, completed_files: dict[str, str]
    ) -> dict:
        """Regex fallback: extract exports without Claude."""
        files: list[dict] = []
        for path, content in completed_files.items():
            if not path.endswith(".py"):
                continue
            exports: dict[str, list[str]] = {
                "classes": _CLASS_RE.findall(content),
                "functions": _FUNC_RE.findall(content),
                "constants": _CONST_RE.findall(content),
                "models": _MODEL_RE.findall(content),
                "routes": _ROUTE_RE.findall(content),
            }
            # Filter out dunder names from functions
            exports["functions"] = [
                f for f in exports["functions"] if not f.startswith("_")
            ]
            files.append({"path": path, "exports": exports})
        return {"layer": layer_num, "files": files}


def _find_similar_name(name: str, name_to_source: dict[str, str]) -> str | None:
    """
    Return the most similar known name to `name` if it looks like a typo.
    Simple edit-distance heuristic: same prefix or off by one character.
    """
    name_lower = name.lower()
    for known in name_to_source:
        known_lower = known.lower()
        if known_lower.startswith(name_lower[:4]) and abs(len(known) - len(name)) <= 3:
            return known
    return None
