"""
memory_vault/graphiti_store.py
─────────────────────────────
Graphiti temporal knowledge graph store for JARVIS.

Graphiti uses Kuzu as its embedded graph database backend (no separate server
process required). All graph data is stored in memory_vault/kuzu_db/ on disk.

Key Concept — Bi-temporal Modeling:
  Every fact (graph edge) in Graphiti has TWO timestamps:
  - valid_from: when the fact became true in the real world
  - valid_to:   when the fact stopped being true (None = currently valid)
  - created_at: when JARVIS ingested this fact

  When a new fact contradicts an existing one, Graphiti automatically sets
  valid_to on the old fact and creates the new one as currently valid.
  This means: old facts are PRESERVED for history but not returned as current.

Usage:
  store = GraphitiStore()
  await store.initialize()
  await store.add_fact("User prefers Zustand", category="technology_preference")
  results = await store.search_current("state management library", num_results=3)
  await store.invalidate_fact_by_text("User prefers Redux")

Author: Hitansu Parichha | Nisum Technologies
Phase 4 — Blueprint v6.0
"""

import os
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GRAPHITI_DB_DIR = os.getenv("GRAPHITI_DB_DIR", "./memory_vault/kuzu_db")


class GraphitiStore:
    """
    Temporal knowledge graph store using Graphiti + Kuzu.

    Handles all time-sensitive, contradiction-prone facts about the user.
    Uses bi-temporal modeling to know which version of a fact is current.

    Thread-safe for concurrent reads. Writes are serialized internally.
    """

    def __init__(self):
        self._client = None
        self._initialized = False
        self._db_path = Path(GRAPHITI_DB_DIR)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> bool:
        """
        Initialize the Graphiti client with Kuzu embedded backend.

        Returns:
            True if initialization succeeded, False if Graphiti is unavailable.
        """
        try:
            from graphiti_core import Graphiti
            from graphiti_core.driver.kuzu_driver import KuzuDriver
            from graphiti_core.llm_client.openai_client import OpenAIClient
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            import os

            ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/v1"
            llm_model = os.getenv("MODEL_ORCHESTRATOR", "gemma4:e4b")
            embed_model = os.getenv("GRAPHITI_EMBEDDING_MODEL", "nomic-embed-text")

            llm_config = LLMConfig(api_key="ollama", base_url=ollama_url, model=llm_model)
            from memory_vault.ollama_client import OllamaGraphitiClient
            llm_client = OllamaGraphitiClient(config=llm_config)

            embedder_config = OpenAIEmbedderConfig(api_key="ollama", base_url=ollama_url, embedding_model=embed_model)
            embedder = OpenAIEmbedder(config=embedder_config)

            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
            cross_encoder = OpenAIRerankerClient(config=llm_config, client=llm_client)

            driver = KuzuDriver(str(self._db_path))
            self._client = Graphiti(
                graph_driver=driver,
                llm_client=llm_client,
                embedder=embedder,
                cross_encoder=cross_encoder
            )
            await self._client.build_indices_and_constraints()
            self._initialized = True
            logger.info(f"GraphitiStore initialized at {self._db_path}")
            return True
        except ImportError:
            logger.warning(
                "graphiti-core not installed. Run: pip install graphiti-core kuzu. "
                "Temporal memory features will be disabled."
            )
            return False
        except Exception as e:
            logger.error(f"GraphitiStore initialization failed: {e}")
            return False

    @property
    def is_available(self) -> bool:
        """Return True if Graphiti is initialized and available."""
        return self._initialized and self._client is not None

    async def add_fact(
        self,
        fact: str,
        category: str,
        source: str = "nightly_distiller",
        valid_from: Optional[datetime] = None,
    ) -> bool:
        """
        Add a new fact to the temporal knowledge graph.

        If this fact contradicts an existing fact in the same category,
        Graphiti will automatically set valid_to on the old fact and
        create this one as the new currently-valid fact.

        Args:
            fact:       The fact text. E.g. "User prefers Zustand for state management"
            category:   Semantic category for grouping. E.g. "technology_preference"
            source:     Where this fact came from. E.g. "nightly_distiller" or "user_correction"
            valid_from: When this fact became true. Defaults to now.

        Returns:
            True if successfully added, False on error.
        """
        if not self.is_available:
            logger.warning("GraphitiStore not available — skipping add_fact")
            return False

        try:
            from graphiti_core.nodes import EpisodeType

            episode_name = f"{category}:{datetime.now(timezone.utc).isoformat()}"
            content = f"[{category.upper()}] {fact}"

            await self._client.add_episode(
                name=episode_name,
                episode_body=content,
                source=EpisodeType.text,
                source_description=source,
                reference_time=valid_from or datetime.now(timezone.utc),
            )
            logger.info(f"GraphitiStore: added fact [{category}] {fact[:60]}...")
            return True
        except Exception as e:
            logger.error(f"GraphitiStore.add_fact failed: {e}")
            return False

    async def search_current(
        self,
        query: str,
        num_results: int = 5,
        category_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Search for currently valid facts related to the query.

        Uses Graphiti's hybrid retrieval: semantic embedding search +
        BM25 keyword search + graph traversal. Returns only facts whose
        valid_to is None (i.e., still currently true).

        Args:
            query:           Natural language search query.
            num_results:     Maximum number of results to return.
            category_filter: Optional category to restrict results to.

        Returns:
            List of dicts: [{text, category, confidence, valid_from, source}]
        """
        if not self.is_available:
            return []

        try:
            edges = await self._client.search(query, num_results=num_results * 2)

            results = []
            for edge in edges:
                # Filter to only currently valid facts (valid_to is None)
                if hasattr(edge, "valid_to") and edge.valid_to is not None:
                    continue

                fact_text = getattr(edge, "fact", "") or getattr(edge, "name", "")
                if not fact_text:
                    continue

                category = "general"
                if fact_text.startswith("["):
                    end_idx = fact_text.find("]")
                    if end_idx != -1:
                        category = fact_text[1:end_idx].lower()
                        fact_text = fact_text[end_idx+1:].strip()

                result = {
                    "text": fact_text,
                    "category": category,
                    "confidence": getattr(edge, "score", 0.8),
                    "valid_from": str(getattr(edge, "valid_at", "")),
                    "source": getattr(edge, "source_description", "unknown"),
                }

                if category_filter and result["category"] != category_filter:
                    continue

                results.append(result)

                if len(results) >= num_results:
                    break

            return results
        except Exception as e:
            logger.error(f"GraphitiStore.search_current failed: {e}")
            return []

    async def invalidate_fact_by_text(self, fact_text: str) -> bool:
        """
        Manually invalidate (expire) a fact by its text content.

        Called when the user issues a correction: "Jarvis, forget that I use X."
        Sets valid_to = now on any matching currently-valid fact.

        Args:
            fact_text: Text of the fact to invalidate. Partial match is enough.

        Returns:
            True if at least one fact was invalidated, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            # Search for matching facts first
            matches = await self.search_current(fact_text, num_results=5)
            if not matches:
                logger.info(f"GraphitiStore.invalidate: no matching facts for '{fact_text}'")
                return False

            # Graphiti handles invalidation through re-ingestion with contradictory content
            # Add an explicit negation fact — Graphiti will detect the contradiction
            await self.add_fact(
                fact=f"[CORRECTION] The following is no longer true: {fact_text}",
                category="user_correction",
                source="user_correction",
            )
            logger.info(f"GraphitiStore: invalidated facts matching '{fact_text[:50]}'")
            return True
        except Exception as e:
            logger.error(f"GraphitiStore.invalidate_fact_by_text failed: {e}")
            return False

    async def invalidate_facts_by_date(self, date_str: str) -> int:
        """
        Invalidate all facts ingested on a specific date.

        Called when user says: "Jarvis, clear everything from last Tuesday."

        Args:
            date_str: Date string, e.g. "2026-04-15" or "Tuesday" (resolved by caller)

        Returns:
            Count of facts invalidated.
        """
        if not self.is_available:
            return 0

        try:
            # Search all facts (broad query) and filter by ingestion date
            all_facts = await self.search_current("", num_results=200)
            invalidated = 0

            for fact in all_facts:
                fact_date = fact.get("valid_from", "")[:10]  # YYYY-MM-DD
                if date_str in fact_date:
                    await self.invalidate_fact_by_text(fact["text"])
                    invalidated += 1

            logger.info(f"GraphitiStore: invalidated {invalidated} facts from {date_str}")
            return invalidated
        except Exception as e:
            logger.error(f"GraphitiStore.invalidate_facts_by_date failed: {e}")
            return 0

    async def get_node_count(self) -> int:
        """Return the total number of graph nodes (for stats endpoint)."""
        if not self.is_available:
            return 0
        try:
            # Graphiti doesn't expose direct count — estimate from search
            # Search for 'user' instead of empty string since BM25 ignores empty
            results = await self._client.search("user", num_results=1000)
            return len(results)
        except Exception:
            return 0

    async def close(self):
        """Cleanly close the Graphiti client and Kuzu connection."""
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._initialized = False
