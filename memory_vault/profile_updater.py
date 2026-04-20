"""
memory_vault/profile_updater.py
────────────────────────────────
Reads the compiled wiki/user_profile.md and injects a fresh USER PROFILE
summary into JARVIS_CORE.md at gateway startup.

This is the bridge between Tier 4 (Wiki) and Tier 1 (Procedural).
After each nightly distillation, wiki/user_profile.md gets richer.
On next boot, this module reads it and updates the USER PROFILE section
in JARVIS_CORE.md so JARVIS_CORE's KV-cache always has current profile data.

Design decisions:
  - Only updates if wiki/user_profile.md has been written by the distiller
    (i.e., has content beyond the empty stub header).
  - Extracts a compact summary (max 15 lines) to keep JARVIS_CORE.md lean
    and KV-cache-friendly.
  - If wiki/user_profile.md does not exist or is empty, leaves JARVIS_CORE.md
    untouched — the static handwritten profile stays as the fallback.
  - Never overwrites the OPERATING RULES section or any section below USER PROFILE.
  - Writes to user_profile_cache.json as an intermediate artifact so the
    update can be inspected or rolled back without touching JARVIS_CORE.md.

Called from: core_engine/gateway.py lifespan startup hook.

Author: Hitansu Parichha | Nisum Technologies
Phase 4 — Blueprint v6.0
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_JARVIS_DIR = Path(__file__).parent.parent          # jarvis/
JARVIS_CORE_PATH = _JARVIS_DIR / "JARVIS_CORE.md"
WIKI_DIR = Path(os.getenv("WIKI_DIR", "./memory_vault/wiki"))
USER_PROFILE_WIKI = WIKI_DIR / "user_profile.md"
PROFILE_CACHE_PATH = _JARVIS_DIR / "memory_vault" / "user_profile_cache.json"

# Minimum wiki content size to be considered "written by distiller"
# (stubs are ~80 bytes — distilled content is much larger)
MIN_WIKI_CONTENT_BYTES = 150

# Markers in JARVIS_CORE.md that surround the USER PROFILE section
_PROFILE_SECTION_HEADER = "## USER PROFILE"
_PROFILE_SECTION_FOOTER = "---"


def update_jarvis_core_profile(force: bool = False) -> bool:
    """
    Read wiki/user_profile.md and inject a compact summary into JARVIS_CORE.md.

    This runs at gateway startup. It is a best-effort operation — any failure
    is logged but never raises. JARVIS continues booting regardless.

    Args:
        force: If True, update even if wiki content hasn't changed since last run.

    Returns:
        True if JARVIS_CORE.md was updated, False if skipped or failed.
    """
    try:
        # ── Step 1: Check if wiki has distilled content ────────────────────────
        if not USER_PROFILE_WIKI.exists():
            logger.debug("profile_updater: wiki/user_profile.md not found — skipping")
            return False

        wiki_content = USER_PROFILE_WIKI.read_text(encoding="utf-8").strip()
        if len(wiki_content.encode("utf-8")) < MIN_WIKI_CONTENT_BYTES:
            logger.debug("profile_updater: wiki/user_profile.md is still a stub — skipping")
            return False

        # ── Step 2: Check if update is actually needed ─────────────────────────
        cache = _load_profile_cache()
        if not force and cache.get("wiki_hash") == _hash_text(wiki_content):
            logger.debug("profile_updater: wiki unchanged since last update — skipping")
            return False

        # ── Step 3: Extract compact summary from wiki ──────────────────────────
        compact_summary = _extract_compact_summary(wiki_content)
        if not compact_summary:
            logger.warning("profile_updater: could not extract summary from wiki — skipping")
            return False

        # ── Step 4: Read JARVIS_CORE.md ────────────────────────────────────────
        if not JARVIS_CORE_PATH.exists():
            logger.error("profile_updater: JARVIS_CORE.md not found!")
            return False

        core_content = JARVIS_CORE_PATH.read_text(encoding="utf-8")

        # ── Step 5: Replace USER PROFILE section ──────────────────────────────
        updated_core = _replace_profile_section(core_content, compact_summary)
        if updated_core is None:
            logger.warning("profile_updater: USER PROFILE section not found in JARVIS_CORE.md")
            return False

        # ── Step 6: Write back atomically ─────────────────────────────────────
        tmp_path = JARVIS_CORE_PATH.with_suffix(".md.tmp")
        tmp_path.write_text(updated_core, encoding="utf-8")
        tmp_path.replace(JARVIS_CORE_PATH)

        # ── Step 7: Save cache to avoid redundant future updates ───────────────
        _save_profile_cache({
            "wiki_hash": _hash_text(wiki_content),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "summary_lines": len(compact_summary.splitlines()),
        })

        logger.info("profile_updater: JARVIS_CORE.md USER PROFILE section updated from wiki")
        return True

    except Exception as e:
        logger.error(f"profile_updater.update_jarvis_core_profile failed: {e}")
        return False


def _extract_compact_summary(wiki_content: str, max_lines: int = 15) -> str:
    """
    Extract a compact, KV-cache-friendly summary from wiki/user_profile.md.

    Strips the YAML header, trims the ## Summary section, and caps to max_lines
    so JARVIS_CORE.md stays small.

    Args:
        wiki_content: Full content of wiki/user_profile.md
        max_lines: Maximum number of lines in the resulting summary

    Returns:
        Compact summary string, or empty string if extraction failed.
    """
    try:
        lines = wiki_content.splitlines()

        # Skip YAML front-matter (lines between --- markers)
        start_idx = 0
        if lines and lines[0].strip() == "---":
            end_marker = next(
                (i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None
            )
            if end_marker:
                start_idx = end_marker + 1

        content_lines = [l for l in lines[start_idx:] if l.strip()]

        # Remove lines that are just wiki-internal headers like "# JARVIS User Profile Wiki"
        content_lines = [
            l for l in content_lines
            if not l.strip().startswith("# JARVIS")
            and not l.strip().startswith("# Auto-generated")
            and not l.strip().startswith("# Last updated")
        ]

        if not content_lines:
            return ""

        # Cap to max_lines
        if len(content_lines) > max_lines:
            content_lines = content_lines[:max_lines]
            content_lines.append("  [See wiki/user_profile.md for full profile]")

        return "\n".join(f"  {l}" if not l.startswith("  ") else l for l in content_lines)

    except Exception as e:
        logger.error(f"profile_updater._extract_compact_summary failed: {e}")
        return ""


def _replace_profile_section(core_content: str, new_summary: str) -> Optional[str]:
    """
    Replace the content between ## USER PROFILE and the next --- in JARVIS_CORE.md.

    Args:
        core_content: Full text of JARVIS_CORE.md
        new_summary:  The compact summary to inject

    Returns:
        Updated JARVIS_CORE.md content, or None if the section was not found.
    """
    # Find the USER PROFILE header
    profile_start = core_content.find(_PROFILE_SECTION_HEADER)
    if profile_start == -1:
        return None

    # Find the next --- after the USER PROFILE header
    search_from = profile_start + len(_PROFILE_SECTION_HEADER)
    next_divider = core_content.find("\n---", search_from)
    if next_divider == -1:
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    new_section = (
        f"{_PROFILE_SECTION_HEADER}\n"
        f"# Auto-updated from wiki/user_profile.md at {timestamp}\n"
        f"# Full profile: memory_vault/wiki/user_profile.md\n\n"
        f"{new_summary}\n"
    )

    return core_content[:profile_start] + new_section + core_content[next_divider:]


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _load_profile_cache() -> dict:
    """Load the profile update cache from disk."""
    try:
        if PROFILE_CACHE_PATH.exists():
            return json.loads(PROFILE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_profile_cache(data: dict) -> None:
    """Save the profile update cache to disk."""
    try:
        PROFILE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"profile_updater: failed to save cache: {e}")


def _hash_text(text: str) -> str:
    """Return a lightweight hash of text for change detection."""
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()
