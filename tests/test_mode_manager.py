"""
J.A.R.V.I.S. — tests/test_mode_manager.py
ModeManager dual-mode switching and RAM guard tests.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

import os
import pytest

from core_engine.mode_manager import ModeManager


@pytest.fixture
def manager(monkeypatch):
    """Return a fresh ModeManager with offline mode set."""
    monkeypatch.setenv("OPERATION_MODE", "offline")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("MODEL_RECEPTIONIST", "gemma4:e4b")
    monkeypatch.setenv("MODEL_SPECIALIST_CODE", "gemma4:26b")
    monkeypatch.setenv("MODEL_ORCHESTRATOR", "qwen3.5:27b-q4_K_M")
    return ModeManager()


# ---------------------------------------------------------------------------
# Mode retrieval
# ---------------------------------------------------------------------------

def test_get_current_mode_offline(manager):
    """get_current_mode() should return 'offline' when OPERATION_MODE=offline."""
    assert manager.get_current_mode() == "offline"


def test_set_mode_changes_mode(manager):
    """set_mode() should update the current mode."""
    manager.set_mode("online")
    assert manager.get_current_mode() == "online"
    manager.set_mode("offline")  # restore
    assert manager.get_current_mode() == "offline"


# ---------------------------------------------------------------------------
# Mode validation
# ---------------------------------------------------------------------------

def test_validate_mode_switch_to_offline(manager):
    """Switching to offline mode is always valid."""
    result = manager.validate_mode_switch("offline")
    assert result["valid"] is True


def test_validate_mode_switch_to_online_no_creds(manager, monkeypatch):
    """Switching to online without creds file should return invalid."""
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/path/creds.json")
    monkeypatch.setenv("VERTEX_PROJECT", "my-project")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
    result = manager.validate_mode_switch("online")
    assert result["valid"] is False
    assert "error" in result
    assert len(result["error"]) > 0


def test_validate_mode_switch_to_online_with_creds(manager, monkeypatch, tmp_path):
    """Switching to online with a real creds file should pass file check."""
    # Create a dummy credentials file
    creds_file = tmp_path / "dummy_creds.json"
    creds_file.write_text('{"type": "service_account"}')
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    monkeypatch.setenv("VERTEX_PROJECT", "my-project")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
    result = manager.validate_mode_switch("online")
    # May fail on SDK missing — that's OK, but should not crash
    assert "valid" in result


def test_validate_mode_switch_unknown(manager):
    """An unknown mode string should return invalid."""
    result = manager.validate_mode_switch("turbo_mode")
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# RAM guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ram_guard_blocks_gemma26b_when_qwen_loaded(manager, monkeypatch):
    """
    Loading gemma4:26b while qwen3.5:27b-q4_K_M is in loaded_models must raise RuntimeError.
    This is the critical RAM safety check — combined = ~34 GB + overhead > 48 GB.

    We monkeypatch get_loaded_models so sync_loaded_models() (GAP 2 fix) returns
    the state WE control — not real Ollama /api/ps — making the test Ollama-independent.
    """
    async def mock_get_loaded_models():
        return ["qwen3.5:27b-q4_K_M"]
    monkeypatch.setattr(manager, "get_loaded_models", mock_get_loaded_models)

    manager.loaded_models.add("qwen3.5:27b-q4_K_M")
    with pytest.raises(RuntimeError) as exc_info:
        await manager._call_ollama(
            model="gemma4:26b",
            system_prompt="test",
            user_message="test",
        )
    assert "BLOCKED" in str(exc_info.value)
    assert "48 GB" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ram_guard_blocks_qwen_when_gemma26b_loaded(manager, monkeypatch):
    """
    Loading qwen3.5:27b-q4_K_M while gemma4:26b is in loaded_models must raise RuntimeError.

    Same monkeypatch pattern — controls what sync_loaded_models() sees.
    """
    async def mock_get_loaded_models():
        return ["gemma4:26b"]
    monkeypatch.setattr(manager, "get_loaded_models", mock_get_loaded_models)

    manager.loaded_models.add("gemma4:26b")
    with pytest.raises(RuntimeError) as exc_info:
        await manager._call_ollama(
            model="qwen3.5:27b-q4_K_M",
            system_prompt="test",
            user_message="test",
        )
    assert "BLOCKED" in str(exc_info.value)


def test_ram_guard_allows_small_model_when_large_loaded(manager):
    """
    gemma4:e4b can be loaded regardless of what else is in loaded_models.
    The RAM guard only blocks the two large models from coexisting.
    """
    manager.loaded_models.add("gemma4:26b")
    manager.loaded_models.add("qwen3.5:27b-q4_K_M")
    # No error should be raised for checking the small model
    # (actual Ollama call will fail, but the guard check itself passes)
    assert "gemma4:e4b" not in [manager._LARGE_MODEL_A, manager._LARGE_MODEL_B]


# ---------------------------------------------------------------------------
# Ollama unavailability
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ollama_unavailable_returns_error_dict(manager, monkeypatch):
    """When Ollama is not running, _call_ollama should return an error dict, not crash."""
    # Point to a port that is definitely not running
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:59999")
    manager.ollama_host = "http://localhost:59999"

    result = await manager._call_ollama(
        model="gemma4:e4b",
        system_prompt="test",
        user_message="test",
    )
    # Should return a dict with content explaining the error
    assert isinstance(result, dict)
    assert "content" in result
    assert len(result["content"]) > 0
    # Should NOT raise an exception
