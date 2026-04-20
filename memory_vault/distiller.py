"""
memory_vault/distiller.py
──────────────────────────
Nightly memory distillation job for JARVIS.

Runs at 2:00 AM daily (via APScheduler). Reads the day's conversation log,
calls the distiller LLM to extract structured facts, and writes those facts to:
  1. ChromaDB (vector embeddings for semantic search)
  2. Graphiti (temporal graph for contradiction resolution)
  3. Wiki markdown files (compiled human-readable knowledge base)

This module is the ONLY thing that reads raw logs. Nothing else touches logs.
The gateway reads only ChromaDB/Graphiti/Wiki — never the raw log files.

Author: Hitansu Parichha | Nisum Technologies
Phase 4 — Blueprint v6.0
"""

import os
import json
import logging
import re
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOG_DIR = Path(os.getenv("LOG_DIR", "./memory_vault/logs"))
WIKI_DIR = Path(os.getenv("WIKI_DIR", "./memory_vault/wiki"))
DISTILLER_FORCE_THRESHOLD_MB = float(os.getenv("DISTILLER_FORCE_THRESHOLD_MB", "50"))

# Maps fact category → wiki file name
CATEGORY_TO_WIKI = {
    "technology_preference":  "coding_style",
    "tool_preference":        "coding_style",
    "coding_habit":           "coding_style",
    "coding_style":           "coding_style",
    "project":                "projects",
    "current_project":        "projects",
    "deadline":               "projects",
    "shopping_preference":    "shopping_patterns",
    "shopping":               "shopping_patterns",
    "product_preference":     "shopping_patterns",
    "daily_pattern":          "daily_patterns",
    "routine":                "daily_patterns",
    "schedule":               "daily_patterns",
    "user_preference":        "user_profile",
    "general":                "user_profile",
    "user_correction":        "corrections",
}

# Distiller LLM prompt template — full version in prompts/memory_distiller.txt
_EXTRACTION_PROMPT = """You are JARVIS's memory distillation engine. Extract structured personal facts from the conversation below.

Return ONLY a JSON array. Each element must have:
- "fact": string — a single, clear, specific personal fact about the user
- "category": one of: technology_preference, tool_preference, coding_habit, coding_style, project, current_project, deadline, shopping_preference, shopping, product_preference, daily_pattern, routine, schedule, user_preference, general, user_correction
- "confidence": float 0.0-1.0

Rules:
- Only extract PERSONAL facts about the user, never general knowledge
- Each fact must be a complete sentence
- Exclude greetings, system messages, filler
- If no facts, return []

Conversation:
{conversation}

JSON array:"""


class MemoryDistiller:
    """
    Nightly distillation job — reads raw logs, extracts facts, updates all stores.
    """

    def __init__(self, chroma_store, graphiti_store, mode_manager):
        self._chroma = chroma_store
        self._graphiti = graphiti_store
        self._mode_manager = mode_manager
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        WIKI_DIR.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        target_date: Optional[date] = None,
        force: bool = False,
    ) -> dict:
        """
        Execute the full distillation pipeline for the given date.

        Args:
            target_date: Date to process. Defaults to today.
            force:       Force distillation even if already done today.

        Returns:
            Summary dict: {status, facts_extracted, written_to_chroma,
                           written_to_graphiti, wiki_sections_updated}
        """
        target_date = target_date or date.today()
        log_file = LOG_DIR / f"{target_date.isoformat()}.log"

        if not log_file.exists():
            logger.info(f"Distiller: no log file for {target_date} — nothing to do")
            return {"status": "no_log_file", "date": target_date.isoformat()}

        # Check if already distilled today (unless forced)
        distillation_marker = LOG_DIR / f"distillation_{target_date.isoformat()}.log"
        if distillation_marker.exists() and not force:
            logger.info(f"Distiller: already ran for {target_date} — skipping (use force=True)")
            return {"status": "already_distilled", "date": target_date.isoformat()}

        log_content = log_file.read_text(encoding="utf-8")
        if not log_content.strip():
            return {"status": "empty_log", "date": target_date.isoformat()}

        logger.info(f"Distiller: processing {log_file.name} ({len(log_content)} bytes)")

        # Extract facts via LLM
        facts = await self._extract_facts(log_content)
        logger.info(f"Distiller: extracted {len(facts)} facts")

        written_chroma = 0
        written_graphiti = 0
        wiki_sections = set()

        for fact_obj in facts:
            fact_text = fact_obj.get("fact", "").strip()
            category = fact_obj.get("category", "general")
            confidence = float(fact_obj.get("confidence", 0.7))

            if not fact_text or confidence < 0.6:
                continue

            # Write to ChromaDB
            if self._chroma.is_available:
                ok = self._chroma.add_fact(
                    fact=fact_text,
                    category=category,
                    metadata={"confidence": confidence, "distilled_from": log_file.name},
                )
                if ok:
                    written_chroma += 1

            # Write to Graphiti
            if self._graphiti.is_available:
                ok = await self._graphiti.add_fact(
                    fact=fact_text,
                    category=category,
                    source="nightly_distiller",
                )
                if ok:
                    written_graphiti += 1

            # Track which wiki sections need updating
            wiki_file = CATEGORY_TO_WIKI.get(category, "user_profile")
            wiki_sections.add(wiki_file)

        # Update wiki sections
        for section in wiki_sections:
            await self._update_wiki_section(section, facts)

        # Write distillation summary log
        summary = {
            "status": "ok",
            "date": target_date.isoformat(),
            "facts_extracted": len(facts),
            "written_to_chroma": written_chroma,
            "written_to_graphiti": written_graphiti,
            "wiki_sections_updated": list(wiki_sections),
        }

        with open(distillation_marker, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info(
            f"Distiller: done. {len(facts)} facts → "
            f"ChromaDB:{written_chroma} Graphiti:{written_graphiti} "
            f"Wiki:{list(wiki_sections)}"
        )
        return summary

    async def _extract_facts(self, conversation_text: str) -> list[dict]:
        """
        Call the distiller LLM to extract structured facts from conversation text.

        Args:
            conversation_text: Raw log file content.

        Returns:
            List of fact dicts: [{fact, category, confidence}]
        """
        try:
            prompt = _EXTRACTION_PROMPT.format(conversation=conversation_text[:8000])
            response = await self._mode_manager.complete(
                prompt=prompt,
                model_override=os.getenv("MODEL_MEMORY_DISTILLER", "gemma4:e4b"),
                max_tokens=2000,
                temperature=0.1,
            )

            response_text = response.get("text", "") if isinstance(response, dict) else str(response)

            # Extract JSON array from response (model may include extra text)
            json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
            if not json_match:
                logger.warning("Distiller: LLM returned no JSON array")
                return []

            facts = json.loads(json_match.group(0))
            if not isinstance(facts, list):
                return []

            return facts
        except json.JSONDecodeError as e:
            logger.warning(f"Distiller: JSON parse error: {e}")
            return []
        except Exception as e:
            logger.error(f"Distiller._extract_facts failed: {e}")
            return []

    async def _update_wiki_section(self, section_name: str, all_facts: list[dict]) -> bool:
        """
        Append newly distilled facts to the relevant wiki section file.

        Args:
            section_name: Wiki file name without extension (e.g., "coding_style")
            all_facts:    All facts extracted in this distillation run.

        Returns:
            True on success.
        """
        wiki_file = WIKI_DIR / f"{section_name}.md"

        # Filter facts relevant to this wiki section
        relevant_categories = [
            cat for cat, wiki in CATEGORY_TO_WIKI.items() if wiki == section_name
        ]
        relevant_facts = [
            f for f in all_facts
            if f.get("category", "general") in relevant_categories
            and f.get("confidence", 0) >= 0.6
        ]

        if not relevant_facts:
            return True

        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Read existing content
            existing = ""
            if wiki_file.exists():
                existing = wiki_file.read_text(encoding="utf-8")
            else:
                existing = f"---\n# JARVIS {section_name.replace('_', ' ').title()} Wiki\n# Auto-generated by nightly distillation job.\n---\n\n"

            # Build new entries block
            new_entries = f"\n## Distillation: {timestamp}\n"
            for fact in relevant_facts:
                new_entries += f"- {fact['fact']}\n"

            wiki_file.write_text(existing + new_entries, encoding="utf-8")
            logger.info(f"Distiller: updated wiki/{section_name}.md with {len(relevant_facts)} facts")
            return True
        except Exception as e:
            logger.error(f"Distiller._update_wiki_section failed for {section_name}: {e}")
            return False


def setup_distiller_scheduler(distiller: MemoryDistiller):
    """
    Configure and start the APScheduler job to run distillation at 2:00 AM daily.

    Args:
        distiller: Initialized MemoryDistiller instance.

    Returns:
        The started BackgroundScheduler, or None if APScheduler unavailable.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import asyncio

        def _run_distillation():
            """Sync wrapper for the async distillation job."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(distiller.run())
                logger.info(f"Scheduled distillation result: {result.get('status')}")
            except Exception as e:
                logger.error(f"Scheduled distillation failed: {e}")
            finally:
                loop.close()

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_distillation,
            trigger="cron",
            hour=2,
            minute=0,
            id="nightly_distillation",
            name="JARVIS Nightly Memory Distillation",
            max_instances=1,
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Distiller: nightly job scheduled for 02:00 AM daily")
        return scheduler
    except ImportError:
        logger.warning("APScheduler not installed — nightly distillation job will not run automatically")
        return None
    except Exception as e:
        logger.error(f"setup_distiller_scheduler failed: {e}")
        return None
