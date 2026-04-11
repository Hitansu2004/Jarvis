"""
J.A.R.V.I.S. — tests/test_agent_registry.py
AgentRegistry loading, lookup, and system prompt tests.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

import pytest

from core_engine.agent_registry import AgentRegistry


@pytest.fixture(scope="module")
def registry():
    """Return a shared AgentRegistry loaded once per test module."""
    return AgentRegistry()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_loads_13_agents(registry):
    """Registry must load exactly 13 agents from agents.json."""
    assert registry.agent_count == 13, (
        f"Expected 13 agents, got {registry.agent_count}"
    )


def test_all_agents_have_required_fields(registry):
    """Every agent must have all 6 required fields."""
    required_fields = {
        "name", "model_offline", "model_online",
        "system_prompt_file", "trigger_keywords", "enabled",
    }
    for agent in registry.list_agents(enabled_only=False):
        missing = required_fields - set(agent.keys())
        assert not missing, (
            f"Agent '{agent.get('name', '?')}' missing fields: {missing}"
        )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def test_get_agent_by_name(registry):
    """get_agent('receptionist') must return the correct agent dict."""
    agent = registry.get_agent("receptionist")
    assert agent is not None
    assert agent["name"] == "receptionist"
    assert agent["model_offline"] == "gemma4:e4b"
    assert agent["enabled"] is True


def test_get_agent_unknown_returns_none(registry):
    """get_agent('nonexistent') must return None."""
    agent = registry.get_agent("nonexistent_agent_xyz")
    assert agent is None


# ---------------------------------------------------------------------------
# Privacy rules
# ---------------------------------------------------------------------------

def test_voice_triage_always_local(registry):
    """
    voice_triage agent must have model_online == model_offline == gemma4:e4b.
    This is a hard privacy rule — voice commands never go to the cloud.
    """
    agent = registry.get_agent("voice_triage")
    assert agent is not None
    assert agent["model_offline"] == "gemma4:e4b", (
        f"voice_triage model_offline should be gemma4:e4b, got {agent['model_offline']}"
    )
    assert agent["model_online"] == "gemma4:e4b", (
        f"voice_triage model_online should be gemma4:e4b, got {agent['model_online']} — PRIVACY VIOLATION"
    )


# ---------------------------------------------------------------------------
# Specific agent properties
# ---------------------------------------------------------------------------

def test_code_specialist_low_temperature(registry):
    """code_specialist must have temperature 0.1 (precision over creativity)."""
    agent = registry.get_agent("code_specialist")
    assert agent is not None
    assert agent["temperature"] == 0.1, (
        f"code_specialist temperature should be 0.1, got {agent['temperature']}"
    )


def test_receptionist_always_on(registry):
    """receptionist keep_alive_offline should be -1 (never unloaded)."""
    agent = registry.get_agent("receptionist")
    assert agent is not None
    assert agent["keep_alive_offline"] == -1, (
        "receptionist should never be unloaded (keep_alive_offline = -1)"
    )


def test_orchestrator_and_code_specialist_on_demand(registry):
    """orchestrator and code_specialist must be on-demand (keep_alive_offline = 0)."""
    for name in ("orchestrator", "code_specialist"):
        agent = registry.get_agent(name)
        assert agent is not None
        assert agent["keep_alive_offline"] == 0, (
            f"{name} should be on-demand (keep_alive_offline = 0), "
            f"got {agent['keep_alive_offline']}"
        )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def test_system_prompt_includes_jarvis_core(registry):
    """get_system_prompt('receptionist') must begin with JARVIS_CORE.md content."""
    prompt = registry.get_system_prompt("receptionist")
    assert "J.A.R.V.I.S." in prompt, "System prompt must contain JARVIS identity."
    assert "JARVIS" in prompt[:500], (
        "JARVIS_CORE.md must be prepended at the very start of the system prompt."
    )


def test_system_prompt_unknown_agent_returns_core_only(registry):
    """get_system_prompt for an unknown agent returns JARVIS_CORE.md content."""
    prompt = registry.get_system_prompt("ghost_agent_xyz")
    assert "J.A.R.V.I.S." in prompt


# ---------------------------------------------------------------------------
# Hot reload
# ---------------------------------------------------------------------------

def test_reload_works(registry):
    """reload() should return 13 after a clean reload."""
    count = registry.reload()
    assert count == 13, f"Expected 13 after reload, got {count}"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_enabled_filter(registry):
    """list_agents(enabled_only=True) must return only enabled agents."""
    enabled = registry.list_agents(enabled_only=True)
    for agent in enabled:
        assert agent["enabled"] is True, (
            f"Disabled agent '{agent['name']}' appeared in enabled-only list."
        )


def test_list_all_agents(registry):
    """list_agents(enabled_only=False) must return all 13 agents."""
    all_agents = registry.list_agents(enabled_only=False)
    assert len(all_agents) == 13
