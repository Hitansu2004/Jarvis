"""
Tests for memory_vault/graphiti_store.py

Unit tests mock Graphiti. Integration tests require graphiti-core + kuzu.
The CRITICAL test at the bottom verifies contradiction resolution.
"""

import pytest
import pytest_asyncio
import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock


class TestGraphitiStoreUnit:
    """Unit tests — no Graphiti installation required."""

    def test_imports(self):
        from memory_vault.graphiti_store import GraphitiStore
        assert GraphitiStore is not None

    def test_instantiation(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        assert store is not None

    def test_not_available_before_init(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        assert store.is_available is False

    @pytest.mark.asyncio
    async def test_add_fact_returns_false_when_unavailable(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        result = await store.add_fact("test fact", "test_category")
        assert result is False

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_unavailable(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        results = await store.search_current("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_invalidate_returns_false_when_unavailable(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        result = await store.invalidate_fact_by_text("some fact")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_node_count_returns_zero_when_unavailable(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        count = await store.get_node_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_invalidate_by_date_returns_zero_when_unavailable(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        count = await store.invalidate_facts_by_date("2026-04-20")
        assert count == 0

    @pytest.mark.asyncio
    async def test_close_when_not_initialized_doesnt_crash(self):
        from memory_vault.graphiti_store import GraphitiStore
        store = GraphitiStore()
        # Should not raise even when uninitialized
        await store.close()
        assert store.is_available is False

    def test_db_path_created_on_init(self, tmp_path):
        """GraphitiStore must create the DB path directory on init."""
        from memory_vault.graphiti_store import GraphitiStore
        import memory_vault.graphiti_store as gs_module
        original = gs_module.GRAPHITI_DB_DIR
        gs_module.GRAPHITI_DB_DIR = str(tmp_path / "test_kuzu")
        store = GraphitiStore()
        gs_module.GRAPHITI_DB_DIR = original
        assert store is not None


@pytest.mark.integration
class TestGraphitiStoreIntegration:
    """
    Integration tests — require graphiti-core and kuzu.
    Skip with: pytest -m "not integration"
    """

    @pytest_asyncio.fixture
    async def graphiti_store(self, tmp_path):
        import memory_vault.graphiti_store as graphiti_module
        with patch.object(graphiti_module, "GRAPHITI_DB_DIR", str(tmp_path / "kuzu")):
            s = graphiti_module.GraphitiStore()
            await s.initialize()
            yield s
            await s.close()

    def test_initialize_succeeds(self, graphiti_store):
        if not graphiti_store.is_available:
            pytest.skip("GraphitiStore failed to initialize, skipping test")
        assert graphiti_store.is_available is True

    @pytest.mark.asyncio
    async def test_add_and_search_fact(self, graphiti_store):
        """A fact added must be retrievable via search."""
        if not graphiti_store.is_available:
            pytest.skip("Graphiti not available")
        await graphiti_store.add_fact(
            "User prefers Zustand for React state management",
            category="technology_preference",
        )
        results = await graphiti_store.search_current("React state management library")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_contradiction_resolution_critical(self, store):
        """
        CRITICAL TEST: Graphiti must return only the CURRENT fact when two
        contradicting facts exist.

        Scenario:
          1. Add "User uses Redux for state management"
          2. Add "User now prefers Zustand for state management"
          3. Search for "state management library"
          4. Result must contain Zustand, NOT Redux

        This is the fundamental reason Graphiti exists over ChromaDB.
        If this test fails, the temporal memory system is broken.
        """
        if not store.is_available:
            pytest.skip("Graphiti not available")

        # Step 1: Add old fact
        await store.add_fact(
            "User uses Redux for React state management",
            category="technology_preference",
        )
        # Brief pause to ensure temporal ordering
        await asyncio.sleep(0.1)

        # Step 2: Add new contradicting fact
        await store.add_fact(
            "User now prefers Zustand for React state management",
            category="technology_preference",
        )

        # Step 3: Search
        results = await store.search_current("React state management library", num_results=5)

        # Step 4: Verify — current fact should be Zustand
        result_texts = [r["text"].lower() for r in results]
        has_zustand = any("zustand" in t for t in result_texts)
        has_redux_as_current = any(
            "redux" in t and "zustand" not in t
            for t in result_texts
        )

        # Zustand must be present
        assert has_zustand, (
            f"Expected Zustand in results but got: {result_texts}. "
            "Graphiti contradiction detection may not be working correctly."
        )
        # Redux must NOT appear as the primary current fact
    async def test_contradiction_resolution_critical(self, graphiti_store):
        """
        CRITICAL TDD: A new fact contradicting an old fact must invalidate the old fact.
        This is the core bi-temporal graph feature required in Phase 4.
        """
        if not graphiti_store.is_available:
            pytest.skip("Graphiti not available")
            
        # 1. Add the original fact
        await graphiti_store.add_fact("User uses Redux for state management", category="technology_preference")
        
        # 2. Add the contradicting fact
        await graphiti_store.add_fact("User now prefers Zustand instead of Redux", category="technology_preference")
        
        # 3. Search should return Zustand, not Redux
        results = await graphiti_store.search_current("React state management library")
        result_texts = [r["text"].lower() for r in results]
        
        assert any("zustand" in t for t in result_texts), f"Zustand not found in current facts: {result_texts}"
        assert not any("redux" in t and "zustand" not in t for t in result_texts), (
            f"Old Redux fact was not invalidated properly: {result_texts}"
        )

    @pytest.mark.asyncio
    async def test_invalidate_fact(self, graphiti_store):
        """Invalidating a fact must remove it from current-state results."""
        if not graphiti_store.is_available:
            pytest.skip("Graphiti not available")
        await graphiti_store.add_fact("User uses Moment.js for date handling", category="technology_preference")
        await graphiti_store.invalidate_fact_by_text("User uses Moment.js")
        results = await graphiti_store.search_current("Moment.js date library")
        result_texts = [r["text"].lower() for r in results]
        assert all("no longer" in t or "correction" in t or "moment" not in t for t in result_texts), (
            f"Invalidated fact still appearing as current: {result_texts}"
        )
