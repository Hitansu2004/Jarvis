"""
memory_vault/chroma_store.py
─────────────────────────────
ChromaDB vector store for JARVIS — pure semantic similarity search.

ChromaDB stores embedding vectors. It has NO concept of time.
Use ChromaDB for stable, rarely-changing facts where temporal ordering
does not matter (e.g., "User is price-conscious", "User prefers dark mode").

For facts that change over time (framework preferences, current projects,
deadlines), use GraphitiStore instead — it handles contradictions automatically.

This module is the Tier 3 vector layer. Graphiti is the Tier 3 temporal layer.
Both are queried at retrieval time and their results are combined.

Author: Hitansu Parichha | Nisum Technologies
Phase 4 — Blueprint v6.0
"""

import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./memory_vault/chroma_db")
EMBEDDING_MODEL = os.getenv("GRAPHITI_EMBEDDING_MODEL", "nomic-embed-text")


class ChromaStore:
    """
    ChromaDB wrapper for JARVIS vector memory.

    Provides semantic similarity search over all distilled user facts.
    Works alongside GraphitiStore — this handles the vector layer,
    Graphiti handles the temporal layer.
    """

    COLLECTION_NAME = "jarvis_memory"

    def __init__(self):
        self._client = None
        self._collection = None
        self._embedding_fn = None
        self._initialized = False
        self._persist_dir = CHROMA_PERSIST_DIR
        Path(self._persist_dir).mkdir(parents=True, exist_ok=True)

    def initialize(self) -> bool:
        """
        Initialize ChromaDB with persistent storage and Ollama embeddings.

        Returns:
            True if initialization succeeded, False if ChromaDB unavailable.
        """
        try:
            import chromadb
            from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

            self._client = chromadb.PersistentClient(path=self._persist_dir)

            # Use Ollama embedding model — Qwen3-Embedding-0.6B (fast, good quality)
            self._embedding_fn = OllamaEmbeddingFunction(
                url="http://localhost:11434/api/embeddings",
                model_name=EMBEDDING_MODEL,
            )

            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=self._embedding_fn,
                metadata={"description": "JARVIS personal memory — distilled user facts"},
            )

            self._initialized = True
            count = self._collection.count()
            logger.info(f"ChromaStore initialized. Collection has {count} vectors.")
            return True
        except ImportError:
            logger.warning(
                "chromadb not installed. Run: pip install chromadb. "
                "Vector memory will be disabled."
            )
            return False
        except Exception as e:
            logger.error(f"ChromaStore initialization failed: {e}")
            return False

    @property
    def is_available(self) -> bool:
        """Return True if ChromaDB is initialized and ready."""
        return self._initialized and self._collection is not None

    def add_fact(
        self,
        fact: str,
        category: str,
        fact_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Add a fact vector to ChromaDB.

        Args:
            fact:     The fact text to embed and store.
            category: Category label for filtering (e.g., "coding_habit")
            fact_id:  Optional unique ID. Auto-generated if not provided.
            metadata: Optional extra metadata dict merged with defaults.

        Returns:
            True on success, False on error.
        """
        if not self.is_available:
            return False

        try:
            import uuid
            doc_id = fact_id or f"fact_{uuid.uuid4().hex[:12]}"
            meta = {
                "category": category,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if metadata:
                meta.update(metadata)

            self._collection.upsert(
                documents=[fact],
                ids=[doc_id],
                metadatas=[meta],
            )
            logger.debug(f"ChromaStore: added [{category}] {fact[:60]}")
            return True
        except Exception as e:
            logger.error(f"ChromaStore.add_fact failed: {e}")
            return False

    def search(
        self,
        query: str,
        num_results: int = 5,
        category_filter: Optional[str] = None,
        min_relevance: float = 0.65,
    ) -> list[dict]:
        """
        Search for semantically similar facts.

        Args:
            query:           Natural language query.
            num_results:     Max results to return.
            category_filter: Optional category to filter by.
            min_relevance:   Minimum cosine similarity (0-1). Default 0.65.

        Returns:
            List of dicts: [{text, category, relevance_score, fact_id, created_at}]
        """
        if not self.is_available or not query.strip():
            return []

        try:
            where = {"category": category_filter} if category_filter else None

            results = self._collection.query(
                query_texts=[query],
                n_results=min(num_results * 2, max(1, self._collection.count())),
                where=where,
                include=["documents", "metadatas", "distances"],
            )

            facts = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for doc, meta, dist in zip(docs, metas, distances):
                # ChromaDB returns L2 distance — convert to cosine similarity approx
                relevance = max(0.0, 1.0 - dist)
                if relevance < min_relevance:
                    continue

                facts.append({
                    "text": doc,
                    "category": meta.get("category", "general"),
                    "relevance_score": round(relevance, 3),
                    "fact_id": meta.get("id", ""),
                    "created_at": meta.get("created_at", ""),
                })

                if len(facts) >= num_results:
                    break

            return facts
        except Exception as e:
            logger.error(f"ChromaStore.search failed: {e}")
            return []

    def delete_fact(self, fact_id: str) -> bool:
        """
        Delete a specific fact by ID.

        Args:
            fact_id: The ID of the fact to delete.

        Returns:
            True on success, False on error.
        """
        if not self.is_available:
            return False
        try:
            self._collection.delete(ids=[fact_id])
            logger.info(f"ChromaStore: deleted fact {fact_id}")
            return True
        except Exception as e:
            logger.error(f"ChromaStore.delete_fact failed: {e}")
            return False

    def delete_facts_by_date(self, date_str: str) -> int:
        """
        Delete all facts created on a specific date.

        Args:
            date_str: Date prefix in YYYY-MM-DD format.

        Returns:
            Count of deleted facts.
        """
        if not self.is_available:
            return 0
        try:
            # Query all facts and filter by date
            all_results = self._collection.get(
                include=["metadatas"]
            )
            ids_to_delete = []
            for doc_id, meta in zip(
                all_results.get("ids", []),
                all_results.get("metadatas", [])
            ):
                created = meta.get("created_at", "")
                if created.startswith(date_str):
                    ids_to_delete.append(doc_id)

            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
                logger.info(f"ChromaStore: deleted {len(ids_to_delete)} facts from {date_str}")

            return len(ids_to_delete)
        except Exception as e:
            logger.error(f"ChromaStore.delete_facts_by_date failed: {e}")
            return 0

    def delete_facts_by_content(self, text: str) -> int:
        """
        Search for facts similar to text and delete the best match.

        Used by the FORGET memory correction command. Performs a semantic
        similarity search and removes the closest matching fact.

        Args:
            text: The text to search for and delete (e.g. "Tailwind CSS")

        Returns:
            Count of facts deleted (0 or 1).
        """
        if not self.is_available or not text.strip():
            return 0
        try:
            results = self._collection.query(
                query_texts=[text],
                n_results=3,
                include=["ids", "distances"],
            )
            ids = results.get("ids", [[]])[0]
            if ids:
                best_id = ids[0]  # Closest semantic match
                self._collection.delete(ids=[best_id])
                logger.info(f"ChromaStore: deleted fact matching '{text[:60]}'")
                return 1
            return 0
        except Exception as e:
            logger.error(f"ChromaStore.delete_facts_by_content failed: {e}")
            return 0

    def get_count(self) -> int:
        """Return total number of stored fact vectors."""
        if not self.is_available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear_all(self) -> bool:
        """
        Delete the entire collection. DESTRUCTIVE — requires confirmation.
        Only called by admin commands, never by normal memory flow.
        """
        if not self.is_available:
            return False
        try:
            self._client.delete_collection(self.COLLECTION_NAME)
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=self._embedding_fn,
            )
            logger.warning("ChromaStore: entire collection cleared")
            return True
        except Exception as e:
            logger.error(f"ChromaStore.clear_all failed: {e}")
            return False
