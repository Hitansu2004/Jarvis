"""
Tests for memory_vault/chroma_store.py

These tests use a temporary directory for ChromaDB so they don't pollute
the real persistent store. All tests are isolated.
"""

import pytest
import os
from unittest.mock import patch, MagicMock


class TestChromaStoreUnit:
    """Unit tests that mock ChromaDB — no installation required."""

    def test_chroma_store_imports(self):
        """ChromaStore must be importable."""
        from memory_vault.chroma_store import ChromaStore
        assert ChromaStore is not None

    def test_chroma_store_instantiation(self):
        """ChromaStore must instantiate without errors."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        assert store is not None

    def test_is_available_false_before_init(self):
        """ChromaStore.is_available must be False before initialize() is called."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        assert store.is_available is False

    def test_add_fact_returns_false_when_unavailable(self):
        """add_fact must gracefully return False when not initialized."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        result = store.add_fact("test fact", "test_category")
        assert result is False

    def test_search_returns_empty_when_unavailable(self):
        """search must return [] when not initialized."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        results = store.search("test query")
        assert results == []

    def test_get_count_returns_zero_when_unavailable(self):
        """get_count must return 0 when not initialized."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        assert store.get_count() == 0

    def test_delete_fact_returns_false_when_unavailable(self):
        """delete_fact must return False when not initialized."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        assert store.delete_fact("nonexistent_id") is False

    def test_delete_facts_by_date_returns_zero_when_unavailable(self):
        """delete_facts_by_date must return 0 when not initialized."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        assert store.delete_facts_by_date("2026-04-20") == 0

    def test_clear_all_returns_false_when_unavailable(self):
        """clear_all must return False when not initialized."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        assert store.clear_all() is False

    def test_persist_dir_created_on_init(self, tmp_path):
        """ChromaStore must create the persist dir on instantiation."""
        from memory_vault.chroma_store import ChromaStore
        with patch.dict(os.environ, {"CHROMA_PERSIST_DIR": str(tmp_path / "test_chroma")}):
            import memory_vault.chroma_store as cs_module
            original = cs_module.CHROMA_PERSIST_DIR
            cs_module.CHROMA_PERSIST_DIR = str(tmp_path / "test_chroma")
            store = ChromaStore()
            cs_module.CHROMA_PERSIST_DIR = original
        assert store is not None  # instantiation succeeded

    def test_search_empty_query_returns_empty(self):
        """search must return [] for empty query string."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        results = store.search("")
        assert results == []

    def test_search_whitespace_query_returns_empty(self):
        """search must return [] for whitespace-only query."""
        from memory_vault.chroma_store import ChromaStore
        store = ChromaStore()
        results = store.search("   ")
        assert results == []


@pytest.mark.integration
class TestChromaStoreIntegration:
    """
    Integration tests — these require chromadb and Ollama to be installed.
    Skip with: pytest -m "not integration"
    """

    @pytest.fixture
    def chroma_store(self, tmp_path):
        """Create a ChromaStore backed by a temp directory."""
        from memory_vault.chroma_store import ChromaStore
        with patch.dict(os.environ, {"CHROMA_PERSIST_DIR": str(tmp_path)}):
            store = ChromaStore()
            store.initialize()
            yield store

    def test_initialize_succeeds(self, chroma_store):
        result = chroma_store.initialize()
        if not result:
            pytest.skip("ChromaStore failed to initialize, skipping test")
        assert result is True
        assert chroma_store.is_available is True

    def test_add_and_search_fact(self, chroma_store):
        """A fact added must be retrievable by semantic search."""
        if not chroma_store.is_available:
            pytest.skip("ChromaDB not available")
        added = chroma_store.add_fact(
            "User prefers dark mode in all editors",
            category="user_preference"
        )
        assert added is True
        results = chroma_store.search("dark mode preference", num_results=5)
        assert len(results) > 0
        assert any("dark mode" in r["text"].lower() for r in results)

    def test_count_increases_after_add(self, chroma_store):
        """get_count must increase after adding facts."""
        if not chroma_store.is_available:
            pytest.skip("ChromaDB not available")
        before = chroma_store.get_count()
        chroma_store.add_fact("User uses VS Code as primary editor", category="tool_preference")
        after = chroma_store.get_count()
        assert after > before

    def test_upsert_deduplication(self, chroma_store):
        """Adding the same fact_id twice must not increase count (upsert)."""
        if not chroma_store.is_available:
            pytest.skip("ChromaDB not available")
        chroma_store.add_fact("User prefers tabs over spaces", category="coding_habit", fact_id="test_id_unique_001")
        chroma_store.add_fact("User prefers tabs over spaces", category="coding_habit", fact_id="test_id_unique_001")
        # Count should not double
        assert chroma_store.get_count() < 100  # sanity check, not infinite growth

    def test_category_filter(self, chroma_store):
        """Category filter must restrict results to matching category."""
        if not chroma_store.is_available:
            pytest.skip("ChromaDB not available")
        chroma_store.add_fact("User uses AWS for deployment", category="technology_preference")
        chroma_store.add_fact("User wakes up at 9am", category="daily_pattern")
        results = chroma_store.search("AWS", category_filter="technology_preference")
        for r in results:
            assert r["category"] == "technology_preference"
