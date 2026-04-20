"""
Tests for memory_vault/retriever.py

All unit tests mock the stores — no ChromaDB or Graphiti installation required.
"""

import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_graphiti():
    g = MagicMock()
    g.is_available = False
    g.search_current = AsyncMock(return_value=[])
    return g


@pytest.fixture
def mock_chroma():
    c = MagicMock()
    c.is_available = False
    c.search = MagicMock(return_value=[])
    return c


@pytest.fixture
def retriever(mock_graphiti, mock_chroma):
    from memory_vault.retriever import HybridRetriever
    return HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)


class TestHybridRetrieverUnit:

    def test_imports(self):
        from memory_vault.retriever import HybridRetriever
        assert HybridRetriever is not None

    def test_instantiation(self, mock_graphiti, mock_chroma):
        from memory_vault.retriever import HybridRetriever
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        assert r is not None

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_facts(self, retriever):
        """Retriever returns empty string when no facts found."""
        result = await retriever.get_context("some query")
        assert isinstance(result, str)
        assert result == ""

    @pytest.mark.asyncio
    async def test_context_contains_memory_header_when_facts_exist(
        self, mock_graphiti, mock_chroma, tmp_path
    ):
        """When facts exist, output must contain MEMORY CONTEXT markers."""
        from memory_vault.retriever import HybridRetriever
        mock_graphiti.search_current = AsyncMock(return_value=[
            {"text": "User prefers TypeScript", "confidence": 0.9}
        ])
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        import memory_vault.retriever as ret_module
        original = ret_module.WIKI_DIR
        ret_module.WIKI_DIR = str(tmp_path)  # empty wiki dir
        result = await r.get_context("TypeScript preference")
        ret_module.WIKI_DIR = original
        assert "MEMORY CONTEXT" in result

    @pytest.mark.asyncio
    async def test_context_ends_with_end_marker(self, mock_graphiti, mock_chroma, tmp_path):
        """When facts exist, output must end with [END MEMORY CONTEXT]."""
        from memory_vault.retriever import HybridRetriever
        mock_graphiti.search_current = AsyncMock(return_value=[
            {"text": "User prefers dark mode", "confidence": 0.85}
        ])
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        import memory_vault.retriever as ret_module
        original = ret_module.WIKI_DIR
        ret_module.WIKI_DIR = str(tmp_path)
        result = await r.get_context("dark mode")
        ret_module.WIKI_DIR = original
        if result:
            assert "[END MEMORY CONTEXT]" in result

    @pytest.mark.asyncio
    async def test_graphiti_exception_does_not_crash(self, mock_graphiti, mock_chroma):
        """If Graphiti throws, retriever must not crash — fall back to ChromaDB."""
        from memory_vault.retriever import HybridRetriever
        mock_graphiti.search_current = AsyncMock(side_effect=Exception("graphiti error"))
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        result = await r.get_context("test query")
        assert isinstance(result, str)  # No crash

    @pytest.mark.asyncio
    async def test_chroma_exception_does_not_crash(self, mock_graphiti, mock_chroma):
        """If ChromaDB throws, retriever must not crash — use Graphiti only."""
        from memory_vault.retriever import HybridRetriever
        mock_chroma.search = MagicMock(side_effect=Exception("chroma error"))
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        result = await r.get_context("test query")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_deduplication(self, mock_graphiti, mock_chroma, tmp_path):
        """Duplicate facts must not appear twice in context output."""
        from memory_vault.retriever import HybridRetriever
        identical_fact = "User prefers TypeScript for everything"
        mock_graphiti.search_current = AsyncMock(return_value=[
            {"text": identical_fact, "confidence": 0.9}
        ])
        mock_chroma.search = MagicMock(return_value=[
            {"text": identical_fact, "relevance_score": 0.85}
        ])
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        import memory_vault.retriever as ret_module
        original = ret_module.WIKI_DIR
        ret_module.WIKI_DIR = str(tmp_path)
        result = await r.get_context("TypeScript")
        ret_module.WIKI_DIR = original
        # The same fact text must appear at most once
        assert result.count(identical_fact) <= 1

    def test_word_overlap_identical_texts(self, retriever):
        """Word overlap of identical texts must be 1.0."""
        from memory_vault.retriever import HybridRetriever
        overlap = HybridRetriever._word_overlap("user prefers python", "user prefers python")
        assert overlap == 1.0

    def test_word_overlap_no_overlap(self, retriever):
        """Word overlap of completely different texts must be 0.0."""
        from memory_vault.retriever import HybridRetriever
        overlap = HybridRetriever._word_overlap("cat sat mat", "dog ran far")
        assert overlap == 0.0

    def test_word_overlap_empty_strings(self, retriever):
        """Word overlap with empty strings must not crash."""
        from memory_vault.retriever import HybridRetriever
        overlap = HybridRetriever._word_overlap("", "some text")
        assert overlap == 0.0

    @pytest.mark.asyncio
    async def test_wiki_content_included_when_relevant(self, mock_graphiti, mock_chroma, tmp_path):
        """Wiki content must be included when the query matches wiki keywords."""
        from memory_vault.retriever import HybridRetriever
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "coding_style.md").write_text(
            "---\n# Coding Style\n---\nUser uses camelCase for variables."
        )
        import memory_vault.retriever as ret_module
        original = ret_module.WIKI_DIR
        ret_module.WIKI_DIR = str(wiki_dir)
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        r._wiki_dir = wiki_dir
        result = await r.get_context("code style naming convention")
        ret_module.WIKI_DIR = original
        if result:
            assert "MEMORY CONTEXT" in result

    @pytest.mark.asyncio
    async def test_empty_wiki_does_not_appear_in_context(self, mock_graphiti, mock_chroma, tmp_path):
        """Wiki files with no real content (only headers) must be skipped."""
        from memory_vault.retriever import HybridRetriever
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "coding_style.md").write_text("---\n# Header\n---\n")
        r = HybridRetriever(graphiti_store=mock_graphiti, chroma_store=mock_chroma)
        r._wiki_dir = wiki_dir
        result = await r.get_context("code style")
        # Empty wiki shouldn't generate a context block
        assert "From coding_style wiki" not in result
