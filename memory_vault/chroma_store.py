"""
J.A.R.V.I.S. — memory_vault/chroma_store.py
ChromaDB interface for persistent JARVIS memory. Full implementation in Phase 4.

Uses Qwen3-Embedding-0.6B for semantic embeddings.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CHROMA_DB_PATH = str(Path(__file__).parent / "chroma_db")


class ChromaStore:
    """
    Persistent ChromaDB vector store for JARVIS facts and conversations.

    Phase 1 stub: returns empty results gracefully if ChromaDB is unavailable.
    Phase 4 will activate full embedding + retrieval pipeline with
    Qwen3-Embedding-0.6B via sentence-transformers.
    """

    def __init__(self) -> None:
        """
        Initialise ChromaDB client and embedding model.

        Creates two collections: "jarvis_facts" and "jarvis_conversations".
        Wraps all initialisation in try/except for graceful Phase 1 degradation.
        """
        self._client = None
        self._facts_collection = None
        self._conversations_collection = None
        self._embedder = None
        self._available = False
        self._try_init()

    def _try_init(self) -> None:
        """
        Attempt to initialise ChromaDB and the Qwen3 embedding model.

        Logs a warning and disables memory features if either is unavailable.
        """
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=_CHROMA_DB_PATH)
            self._facts_collection = self._client.get_or_create_collection("jarvis_facts")
            self._conversations_collection = self._client.get_or_create_collection(
                "jarvis_conversations"
            )
            logger.info("ChromaDB initialised at %s.", _CHROMA_DB_PATH)
        except ImportError:
            logger.warning(
                "ChromaDB unavailable — memory features disabled until Phase 4. "
                "Install with: pip install chromadb"
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("ChromaDB init failed: %s — memory features disabled.", exc)
            return

        try:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
            logger.info("Qwen3-Embedding-0.6B loaded for memory retrieval.")
            self._available = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Qwen3-Embedding-0.6B not available: %s — memory retrieval disabled.",
                exc,
            )
            # ChromaDB is available but we cannot embed — partial degradation
            self._available = False

    def _embed(self, text: str) -> list[float]:
        """
        Embed a text string using Qwen3-Embedding-0.6B.

        Args:
            text: Text to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        if self._embedder is None:
            return []
        return self._embedder.encode(text).tolist()

    def store_fact(
        self, fact: str, category: str, confidence: str = "high"
    ) -> str:
        """
        Store a distilled fact in the "jarvis_facts" ChromaDB collection.

        Args:
            fact: The factual statement to store.
            category: One of: coding_habit, tech_preference, work_context,
                      shopping_behavior, daily_pattern, personal_goal.
            confidence: "high", "medium", or "low".

        Returns:
            Document ID string, or empty string if unavailable.
        """
        if not self._available or self._facts_collection is None:
            logger.debug("ChromaDB unavailable — store_fact skipped.")
            return ""

        import uuid
        doc_id = str(uuid.uuid4())
        embedding = self._embed(fact)
        try:
            self._facts_collection.add(
                documents=[fact],
                embeddings=[embedding] if embedding else None,
                metadatas=[{"category": category, "confidence": confidence}],
                ids=[doc_id],
            )
            return doc_id
        except Exception as exc:  # noqa: BLE001
            logger.error("store_fact failed: %s", exc)
            return ""

    def query_facts(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Semantic search for relevant facts in ChromaDB.

        Args:
            query: Natural language query string.
            top_k: Maximum number of results to return.

        Returns:
            List of dicts with keys: fact, category, confidence, distance.
        """
        if not self._available or self._facts_collection is None:
            return []

        embedding = self._embed(query)
        try:
            results = self._facts_collection.query(
                query_embeddings=[embedding] if embedding else None,
                query_texts=[query] if not embedding else None,
                n_results=top_k,
            )
            facts = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, distances):
                facts.append({
                    "fact": doc,
                    "category": meta.get("category", "unknown"),
                    "confidence": meta.get("confidence", "medium"),
                    "distance": dist,
                })
            return facts
        except Exception as exc:  # noqa: BLE001
            logger.error("query_facts failed: %s", exc)
            return []

    def store_conversation(
        self, timestamp: str, role: str, content: str
    ) -> str:
        """
        Store a conversation turn in the "jarvis_conversations" collection.

        Args:
            timestamp: ISO 8601 timestamp of the conversation turn.
            role: "user" or "assistant".
            content: The message content.

        Returns:
            Document ID string, or empty string if unavailable.
        """
        if not self._available or self._conversations_collection is None:
            return ""

        import uuid
        doc_id = str(uuid.uuid4())
        embedding = self._embed(content)
        try:
            self._conversations_collection.add(
                documents=[content],
                embeddings=[embedding] if embedding else None,
                metadatas=[{"timestamp": timestamp, "role": role}],
                ids=[doc_id],
            )
            return doc_id
        except Exception as exc:  # noqa: BLE001
            logger.error("store_conversation failed: %s", exc)
            return ""

    def delete_fact(self, fact_id: str) -> bool:
        """
        Delete a specific fact from ChromaDB by document ID.

        Args:
            fact_id: The document ID to delete.

        Returns:
            True if deleted successfully, False otherwise.
        """
        if not self._available or self._facts_collection is None:
            return False
        try:
            self._facts_collection.delete(ids=[fact_id])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("delete_fact failed for id '%s': %s", fact_id, exc)
            return False

    def list_facts(self, limit: int = 20) -> list[dict]:
        """
        Return the most recent facts for user review.

        Args:
            limit: Maximum number of facts to return.

        Returns:
            List of fact dicts with fact, category, and confidence keys.
        """
        if not self._available or self._facts_collection is None:
            return []
        try:
            results = self._facts_collection.get(limit=limit)
            facts = []
            docs = results.get("documents", [])
            metas = results.get("metadatas", [])
            ids = results.get("ids", [])
            for doc, meta, doc_id in zip(docs, metas, ids):
                facts.append({
                    "id": doc_id,
                    "fact": doc,
                    "category": meta.get("category", "unknown"),
                    "confidence": meta.get("confidence", "medium"),
                })
            return facts
        except Exception as exc:  # noqa: BLE001
            logger.error("list_facts failed: %s", exc)
            return []
