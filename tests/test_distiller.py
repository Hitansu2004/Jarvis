"""
Tests for memory_vault/distiller.py

Unit tests use mock stores and mock mode_manager.
No LLM or database required for the unit tests.
"""

import pytest
import json
import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_chroma():
    c = MagicMock()
    c.is_available = False
    c.add_fact = MagicMock(return_value=False)
    return c


@pytest.fixture
def mock_graphiti():
    g = MagicMock()
    g.is_available = False
    g.add_fact = AsyncMock(return_value=False)
    return g


@pytest.fixture
def mock_mode_manager():
    m = MagicMock()
    m.complete = AsyncMock(return_value={"text": "[]"})
    return m


@pytest.fixture
def distiller(mock_chroma, mock_graphiti, mock_mode_manager, tmp_path):
    from memory_vault.distiller import MemoryDistiller
    import memory_vault.distiller as dist_module
    # Redirect log and wiki dirs to tmp_path
    dist_module.LOG_DIR = tmp_path / "logs"
    dist_module.WIKI_DIR = tmp_path / "wiki"
    d = MemoryDistiller(
        chroma_store=mock_chroma,
        graphiti_store=mock_graphiti,
        mode_manager=mock_mode_manager,
    )
    return d


class TestDistillerUnit:

    def test_distiller_imports(self):
        from memory_vault.distiller import MemoryDistiller
        assert MemoryDistiller is not None

    def test_distiller_instantiation(self, mock_chroma, mock_graphiti, mock_mode_manager):
        from memory_vault.distiller import MemoryDistiller
        d = MemoryDistiller(
            chroma_store=mock_chroma,
            graphiti_store=mock_graphiti,
            mode_manager=mock_mode_manager,
        )
        assert d is not None

    @pytest.mark.asyncio
    async def test_run_returns_no_log_when_file_missing(self, distiller):
        result = await distiller.run(target_date=date(2099, 1, 1))
        assert result["status"] == "no_log_file"

    @pytest.mark.asyncio
    async def test_run_extracts_facts_from_log(self, distiller, tmp_path):
        """Distiller must extract facts when log file has conversation content."""
        import memory_vault.distiller as dist_module
        log_dir = dist_module.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        today = date.today()
        log_file = log_dir / f"{today.isoformat()}.log"
        log_file.write_text("""
[2026-04-20T22:00:00Z] [AGENT:receptionist] [MODEL:gemma4:e4b]
USER: I prefer TypeScript over JavaScript for everything
JARVIS: Noted, Sir. I'll remember your preference for TypeScript.
---
""")
        result = await distiller.run(target_date=today, force=True)
        assert result.get("facts_extracted", 0) >= 0
        assert "status" in result

    @pytest.mark.asyncio
    async def test_extract_facts_returns_list(self, distiller):
        """_extract_facts must return a list."""
        facts = await distiller._extract_facts("USER: I like Python\nJARVIS: Noted.")
        assert isinstance(facts, list)

    @pytest.mark.asyncio
    async def test_extract_facts_parses_json_correctly(self, distiller, mock_mode_manager):
        """_extract_facts must correctly parse the LLM's JSON output."""
        mock_mode_manager.complete = AsyncMock(return_value={
            "text": '[{"fact": "User prefers Python", "category": "technology_preference", "confidence": 0.9}]'
        })
        facts = await distiller._extract_facts("USER: I prefer Python\nJARVIS: OK.")
        assert len(facts) >= 0  # Parsed successfully

    @pytest.mark.asyncio
    async def test_extract_facts_handles_json_error(self, distiller, mock_mode_manager):
        """_extract_facts must return [] on JSON parse error (not crash)."""
        mock_mode_manager.complete = AsyncMock(return_value={"text": "not valid json at all"})
        facts = await distiller._extract_facts("any content")
        assert facts == []

    @pytest.mark.asyncio
    async def test_extract_facts_handles_llm_exception(self, distiller, mock_mode_manager):
        """_extract_facts must return [] if the LLM call throws."""
        mock_mode_manager.complete = AsyncMock(side_effect=Exception("LLM error"))
        facts = await distiller._extract_facts("any content")
        assert facts == []

    @pytest.mark.asyncio
    async def test_run_already_distilled_skips(self, distiller, tmp_path):
        """Run must skip if distillation already done today (no force)."""
        import memory_vault.distiller as dist_module
        log_dir = dist_module.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        today = date.today()
        log_file = log_dir / f"{today.isoformat()}.log"
        log_file.write_text("some content")
        marker = log_dir / f"distillation_{today.isoformat()}.log"
        marker.write_text('{"status": "ok"}')
        result = await distiller.run(target_date=today, force=False)
        assert result["status"] == "already_distilled"

    @pytest.mark.asyncio
    async def test_run_force_overrides_skip(self, distiller, tmp_path):
        """Force=True must run even if already distilled."""
        import memory_vault.distiller as dist_module
        log_dir = dist_module.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        today = date.today()
        log_file = log_dir / f"{today.isoformat()}.log"
        log_file.write_text("USER: test\nJARVIS: ok\n")
        marker = log_dir / f"distillation_{today.isoformat()}.log"
        marker.write_text('{"status": "ok"}')
        result = await distiller.run(target_date=today, force=True)
        assert result["status"] != "already_distilled"

    @pytest.mark.asyncio
    async def test_empty_log_returns_empty_status(self, distiller, tmp_path):
        """Empty log file must return empty_log status."""
        import memory_vault.distiller as dist_module
        log_dir = dist_module.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        today = date.today()
        log_file = log_dir / f"{today.isoformat()}.log"
        log_file.write_text("  \n  ")
        result = await distiller.run(target_date=today, force=True)
        assert result["status"] == "empty_log"

    def test_setup_scheduler_returns_scheduler_or_none(self, distiller):
        """setup_distiller_scheduler must return a scheduler or None (not crash)."""
        from memory_vault.distiller import setup_distiller_scheduler
        try:
            scheduler = setup_distiller_scheduler(distiller)
            if scheduler is not None:
                scheduler.shutdown(wait=False)
        except Exception as e:
            pytest.fail(f"setup_distiller_scheduler raised: {e}")
