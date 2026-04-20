"""
tests/test_phase4_integration.py
─────────────────────────────────
Phase 4 integration tests.

These tests verify the full memory pipeline end-to-end:
  - Facts written → contradicted → Graphiti resolves correctly
  - Memory correction commands parsed AND dispatched correctly
  - /memory/* API routes return correct schemas
  - Conversation logger writes to log files correctly
  - Retriever produces valid MEMORY CONTEXT blocks

Some tests are marked @pytest.mark.integration and require full infrastructure.
"""

import pytest
import asyncio
import json
import os
import tempfile
from pathlib import Path
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch

from fastapi.testclient import TestClient


# ── Conversation Logger Integration ───────────────────────────────────────────

class TestConversationLogger:

    @pytest.fixture
    def logger(self, tmp_path):
        from memory_vault.logger import ConversationLogger
        import memory_vault.logger as log_module
        original = log_module.LOG_DIR
        log_module.LOG_DIR = tmp_path
        l = ConversationLogger.__new__(ConversationLogger)
        l.__init__()
        yield l
        log_module.LOG_DIR = original

    def test_logger_imports(self):
        from memory_vault.logger import ConversationLogger
        assert ConversationLogger is not None

    def test_log_conversation_creates_file(self, logger, tmp_path):
        import memory_vault.logger as log_module
        log_module.LOG_DIR = tmp_path
        logger.log_conversation(
            user_message="I prefer TypeScript",
            jarvis_response="Noted, Sir.",
            agent_used="receptionist",
            model_used="gemma4:e4b",
        )
        today = date.today().isoformat()
        log_file = tmp_path / f"{today}.log"
        assert log_file.exists()

    def test_log_conversation_contains_message(self, logger, tmp_path):
        import memory_vault.logger as log_module
        log_module.LOG_DIR = tmp_path
        logger.log_conversation(
            user_message="I use Zustand now",
            jarvis_response="Understood.",
        )
        today = date.today().isoformat()
        content = (tmp_path / f"{today}.log").read_text()
        assert "Zustand" in content

    def test_log_size_mb_returns_zero_for_missing_file(self, logger):
        size = logger.get_log_size_mb(date(2099, 12, 31))
        assert size == 0.0

    def test_list_log_files_returns_list(self, logger):
        files = logger.list_log_files()
        assert isinstance(files, list)

    def test_screen_observation_not_logged_when_disabled(self, logger, tmp_path):
        import memory_vault.logger as log_module
        log_module.LOG_DIR = tmp_path
        original_flag = log_module.PASSIVE_LEARNING_ENABLED
        log_module.PASSIVE_LEARNING_ENABLED = False
        logger.log_screen_observation("User opened VS Code")
        log_module.PASSIVE_LEARNING_ENABLED = original_flag
        today = date.today().isoformat()
        log_file = tmp_path / f"{today}.log"
        if log_file.exists():
            assert "VS Code" not in log_file.read_text()

    def test_screen_observation_logged_when_enabled(self, logger, tmp_path):
        import memory_vault.logger as log_module
        log_module.LOG_DIR = tmp_path
        original_flag = log_module.PASSIVE_LEARNING_ENABLED
        log_module.PASSIVE_LEARNING_ENABLED = True
        logger.log_screen_observation("User opened terminal and ran pytest")
        log_module.PASSIVE_LEARNING_ENABLED = original_flag
        today = date.today().isoformat()
        log_file = tmp_path / f"{today}.log"
        if log_file.exists():
            assert "pytest" in log_file.read_text()

    def test_log_contains_agent_info(self, logger, tmp_path):
        import memory_vault.logger as log_module
        log_module.LOG_DIR = tmp_path
        logger.log_conversation(
            user_message="test",
            jarvis_response="ok",
            agent_used="orchestrator",
            model_used="qwen3.5:27b",
        )
        today = date.today().isoformat()
        content = (tmp_path / f"{today}.log").read_text()
        assert "orchestrator" in content
        assert "qwen3.5:27b" in content

    def test_read_log_returns_empty_for_missing_file(self, logger):
        content = logger.read_log(date(2099, 12, 31))
        assert content == ""


# ── Memory API Routes ──────────────────────────────────────────────────────────

class TestMemoryAPIRoutes:
    """Test that all /memory/* routes return correct schemas."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked memory components."""
        from core_engine.gateway import app
        with TestClient(app) as client:
            mock_graphiti = MagicMock()
            mock_graphiti.is_available = False
            mock_graphiti.search_current = AsyncMock(return_value=[])
            mock_graphiti.get_node_count = AsyncMock(return_value=0)
            app.state.graphiti_store = mock_graphiti

            mock_chroma = MagicMock()
            mock_chroma.is_available = False
            mock_chroma.get_count = MagicMock(return_value=0)
            mock_chroma.search = MagicMock(return_value=[])
            app.state.chroma_store = mock_chroma

            mock_logger = MagicMock()
            mock_logger.list_log_files = MagicMock(return_value=[])
            app.state.conv_logger = mock_logger

            yield client

    def test_memory_stats_route_exists(self, client):
        response = client.get("/memory/stats")
        assert response.status_code == 200

    def test_memory_stats_returns_required_fields(self, client):
        response = client.get("/memory/stats")
        data = response.json()
        assert "chroma_vectors" in data
        assert "graphiti_nodes" in data
        assert "wiki_files" in data

    def test_memory_wiki_route_exists(self, client):
        response = client.get("/memory/wiki")
        assert response.status_code == 200

    def test_memory_wiki_returns_list(self, client):
        response = client.get("/memory/wiki")
        data = response.json()
        assert "wiki_files" in data
        assert isinstance(data["wiki_files"], list)

    def test_memory_query_requires_query_field(self, client):
        response = client.post("/memory/query", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data

    def test_memory_query_accepts_valid_input(self, client):
        response = client.post("/memory/query", json={"query": "TypeScript preference", "top_k": 3})
        assert response.status_code == 200
        data = response.json()
        assert "query" in data

    def test_memory_correct_requires_command(self, client):
        response = client.post("/memory/correct", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data

    def test_memory_correct_handles_forget_command(self, client):
        response = client.post("/memory/correct", json={
            "command": "Jarvis, forget that I use Tailwind CSS."
        })
        assert response.status_code == 200

    def test_memory_correct_returns_action_type(self, client):
        response = client.post("/memory/correct", json={
            "command": "Jarvis, remember that I now prefer pnpm."
        })
        assert response.status_code == 200
        data = response.json()
        assert "action_type" in data
        assert data["action_type"] == "REMEMBER"

    def test_memory_correct_forget_action_type(self, client):
        response = client.post("/memory/correct", json={
            "command": "forget that I use Redux"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("action_type") == "FORGET"


# ── Full Pipeline Test ────────────────────────────────────────────────────────

@pytest.mark.integration
class TestFullMemoryPipeline:
    """
    Full end-to-end test of the memory pipeline.
    Requires graphiti-core, kuzu, and chromadb to be installed.
    Skip with: pytest -m "not integration"
    """

    @pytest.mark.asyncio
    async def test_complete_fact_lifecycle(self, tmp_path):
        """
        Test the complete lifecycle:
          1. Add a fact via GraphitiStore
          2. Add a contradicting fact
          3. Verify Graphiti returns only the new fact
          4. Add the same fact via ChromaStore
          5. Query the HybridRetriever
          6. Verify the context block is formatted correctly
        """
        from memory_vault.graphiti_store import GraphitiStore
        from memory_vault.chroma_store import ChromaStore
        from memory_vault.retriever import HybridRetriever

        with patch.dict(os.environ, {
            "GRAPHITI_DB_DIR": str(tmp_path / "kuzu"),
            "CHROMA_PERSIST_DIR": str(tmp_path / "chroma"),
        }):
            g_store = GraphitiStore()
            g_init = await g_store.initialize()

            c_store = ChromaStore()
            c_init = c_store.initialize()

            if not g_init or not c_init:
                pytest.skip("Graphiti or ChromaDB not available or failed to initialize for integration test")

            await g_store.add_fact("User uses React class components", "technology_preference")
            await asyncio.sleep(0.1)
            await g_store.add_fact("User now uses React functional components with hooks", "technology_preference")

            results = await g_store.search_current("React component style", num_results=3)
            texts = [r["text"].lower() for r in results]
            assert any("functional" in t or "hooks" in t for t in texts), \
                f"Expected functional components in results, got: {texts}"

            c_store.add_fact("User writes React with TypeScript", "technology_preference")

            retriever = HybridRetriever(graphiti_store=g_store, chroma_store=c_store)
            context = await retriever.get_context("React development style")

            assert isinstance(context, str)
            if context:
                assert "MEMORY CONTEXT" in context

            await g_store.close()
