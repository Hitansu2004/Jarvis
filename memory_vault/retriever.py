"""
memory_vault/retriever.py
──────────────────────────
Hybrid memory retriever for JARVIS — combines all four memory tiers.

At query time, this module:
  1. Reads relevant wiki sections (Tier 4)
  2. Queries Graphiti for current-state facts (Tier 3 temporal)
  3. Queries ChromaDB for similar facts (Tier 3 vector)
  4. Deduplicates and ranks results
  5. Returns a formatted MEMORY CONTEXT block for prompt injection

Usage:
  retriever = HybridRetriever(graphiti_store, chroma_store)
  context_block = await retriever.get_context(query="deployment preferences")
  # Inject context_block into the system prompt before the user message

Author: Hitansu Parichha | Nisum Technologies
Phase 4 — Blueprint v6.0
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WIKI_DIR = os.getenv("WIKI_DIR", "./memory_vault/wiki")
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "5"))
MEMORY_MIN_RELEVANCE = float(os.getenv("MEMORY_MIN_RELEVANCE", "0.65"))

# Maps query keywords to wiki file sections
WIKI_KEYWORD_MAP = {
    "coding_style":    ["code", "style", "camelcase", "indent", "variable", "function",
                        "comment", "pattern", "naming", "lint", "format", "clean"],
    "projects":        ["project", "work", "nisum", "deadline", "repo", "github",
                        "sprint", "task", "service", "api", "auth", "current"],
    "shopping_patterns": ["buy", "price", "shop", "purchase", "product", "brand",
                          "amazon", "deal", "expensive", "value", "review"],
    "daily_patterns":  ["morning", "night", "evening", "coffee", "break", "productive",
                        "schedule", "routine", "time", "hours", "wake"],
    "user_profile":    ["prefer", "like", "want", "goal", "plan", "startup",
                        "language", "framework", "tool", "use", "deploy", "user profile wiki"],
    "corrections":     ["forget", "wrong", "correct", "mistake", "update",
                        "remember", "change", "no longer"],
}


class HybridRetriever:
    """
    Unified memory retriever combining Graphiti + ChromaDB + Wiki.

    This is the single entry point for all memory reads at prompt-construction
    time. Never call graphiti_store.search_current() or chroma_store.search()
    directly from the gateway — always go through this class.
    """

    def __init__(self, graphiti_store, chroma_store):
        self._graphiti = graphiti_store
        self._chroma = chroma_store
        self._wiki_dir = Path(WIKI_DIR)

    async def get_context(
        self,
        query: str,
        top_k: int = MEMORY_TOP_K,
        include_wiki: bool = True,
    ) -> str:
        """
        Get the full MEMORY CONTEXT block for injection into a system prompt.

        Args:
            query:        The user's current message / intent description.
            top_k:        Max total facts to include in the context block.
            include_wiki: Whether to include wiki content (set False for memory stats)

        Returns:
            Formatted multi-line string ready for system prompt injection.
            Returns empty string if no relevant facts are found.
        """
        all_facts = []

        # ── Step 1: Wiki read (fastest — no embedding needed) ───────────────
        if include_wiki:
            wiki_facts = self._read_relevant_wiki_sections(query, max_sections=2)
            for text in wiki_facts:
                all_facts.append({
                    "text": text,
                    "source": "wiki",
                    "relevance": 1.0,  # Wiki is always top priority
                })

        # ── Step 2: Graphiti search (current-state, temporal) ────────────────
        try:
            graphiti_facts = await self._graphiti.search_current(
                query, num_results=top_k
            )
            for f in graphiti_facts:
                all_facts.append({
                    "text": f["text"],
                    "source": "graphiti",
                    "relevance": f.get("confidence", 0.8),
                })
        except Exception as e:
            logger.warning(f"Graphiti retrieval failed (non-critical): {e}")

        # ── Step 3: ChromaDB search (semantic similarity) ────────────────────
        try:
            chroma_facts = self._chroma.search(
                query, num_results=top_k, min_relevance=MEMORY_MIN_RELEVANCE
            )
            for f in chroma_facts:
                all_facts.append({
                    "text": f["text"],
                    "source": "chromadb",
                    "relevance": f.get("relevance_score", 0.7),
                })
        except Exception as e:
            logger.warning(f"ChromaDB retrieval failed (non-critical): {e}")

        # ── Step 4: Deduplicate by text similarity ───────────────────────────
        seen = set()
        unique_facts = []
        for fact in sorted(all_facts, key=lambda x: x["relevance"], reverse=True):
            text_lower = fact["text"].lower().strip()
            # Simple dedup: skip if 80%+ of words overlap with an existing fact
            is_duplicate = False
            for seen_text in seen:
                overlap = self._word_overlap(text_lower, seen_text)
                if overlap > 0.8:
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_facts.append(fact)
                seen.add(text_lower)
            if len(unique_facts) >= top_k:
                break

        if not unique_facts:
            return ""

        # ── Step 5: Format as MEMORY CONTEXT block ───────────────────────────
        lines = ["[MEMORY CONTEXT — from personal knowledge base]"]
        for fact in unique_facts:
            source_label = {"wiki": "wiki", "graphiti": "temporal", "chromadb": "vector"}
            label = source_label.get(fact["source"], fact["source"])
            lines.append(f"• {fact['text']}  [{label}]")
        lines.append("[END MEMORY CONTEXT]")

        return "\n".join(lines)

    def _read_relevant_wiki_sections(self, query: str, max_sections: int = 2) -> list[str]:
        """
        Read wiki file sections relevant to the query.

        Matches query words against WIKI_KEYWORD_MAP to find relevant files.
        Reads the content and returns as a list of text excerpts.

        Args:
            query:        The user's query.
            max_sections: Maximum wiki files to read.

        Returns:
            List of wiki content strings (trimmed to 400 chars each for context).
        """
        if not self._wiki_dir.exists():
            return []

        query_words = set(query.lower().split())
        scored_sections = []

        for section_name, keywords in WIKI_KEYWORD_MAP.items():
            keyword_set = set(k.lower() for k in keywords)
            overlap = len(query_words & keyword_set)
            if overlap > 0:
                wiki_file = self._wiki_dir / f"{section_name}.md"
                if wiki_file.exists():
                    scored_sections.append((overlap, section_name, wiki_file))

        scored_sections.sort(key=lambda x: x[0], reverse=True)
        results = []

        for _, section_name, wiki_file in scored_sections[:max_sections]:
            try:
                content = wiki_file.read_text(encoding="utf-8").strip()
                # Remove YAML front matter (--- headers ---)
                content = re.sub(r"^---.*?---\n", "", content, flags=re.DOTALL)
                content = content.strip()
                if len(content) > 50:  # Skip empty or near-empty wikis
                    # Take first 400 chars — enough context without flooding the prompt
                    excerpt = content[:400].strip()
                    results.append(f"[From {section_name} wiki]\n{excerpt}")
            except Exception as e:
                logger.warning(f"Could not read wiki file {wiki_file}: {e}")

        return results

    @staticmethod
    def _word_overlap(text_a: str, text_b: str) -> float:
        """
        Calculate word overlap ratio between two texts (Jaccard similarity).

        Used for deduplication — if two facts share 80%+ of words, they are
        considered duplicates and only the higher-relevance one is kept.
        """
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)
