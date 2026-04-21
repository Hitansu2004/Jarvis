"""
J.A.R.V.I.S. — tests/test_gateway.py
FastAPI gateway endpoint tests.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

import pytest
from fastapi.testclient import TestClient

# Import the FastAPI app
from core_engine.gateway import app

# Use the context manager so the lifespan runs and singletons are initialized
@pytest.fixture(scope="module")
def client():
    # Mock GraphitiStore entirely to prevent Kuzu DB segfault in gateway tests
    from unittest.mock import patch
    import memory_vault.graphiti_store as gs
    import core_engine.gateway as gw
    
    class MockStoreForGateway:
        def __init__(self):
            self.is_available = True
        async def initialize(self): return True
        async def search_current(self, *args, **kwargs): return []
        async def add_fact(self, *args, **kwargs): return True
        async def close(self): pass
        
    with patch.object(gw, "GraphitiStore", MockStoreForGateway, create=True), \
         patch.object(gs, "GraphitiStore", MockStoreForGateway):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    """GET /health must return 200 with 'alive' status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status_endpoint(client):
    """GET /status must return the correct schema."""
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "mode" in data
    assert "prototype_mode" in data
    assert "ollama_alive" in data
    assert "vertex_configured" in data
    assert "agents_loaded" in data
    assert "models_available" in data
    assert isinstance(data["agents_loaded"], int)
    assert isinstance(data["models_available"], list)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def test_agents_endpoint(client):
    """GET /agents must return a list of exactly 13 agents."""
    response = client.get("/agents")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert isinstance(data["agents"], list)
    assert len(data["agents"]) == 13


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def test_chat_endpoint_offline(client, monkeypatch):
    """POST /chat with a simple message returns the correct response schema."""
    # Monkeypatch ModeManager.complete to avoid real Ollama call
    async def mock_complete(*args, **kwargs):
        return {
            "content": "Good morning, Sir. Systems nominal.",
            "model_used": "gemma4:e4b",
            "mode": "offline",
            "tokens_in": 10,
            "tokens_out": 8,
        }

    from core_engine import mode_manager as mm
    monkeypatch.setattr(mm.ModeManager, "complete", mock_complete)

    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "agent_used" in data
    assert "model_used" in data
    assert "complexity_score" in data
    assert "mode" in data
    assert isinstance(data["complexity_score"], int)
    assert 1 <= data["complexity_score"] <= 10


def test_chat_endpoint_requires_message(client):
    """POST /chat with an empty message must return 422."""
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_chat_endpoint_missing_message(client):
    """POST /chat with no body must return 422."""
    response = client.post("/chat", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Mode switch
# ---------------------------------------------------------------------------

def test_mode_switch_offline(client):
    """POST /mode {'mode': 'offline'} must return status 'switched'."""
    response = client.post("/mode", json={"mode": "offline"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "switched"
    assert data["mode"] == "offline"


def test_mode_switch_online_without_creds(client):
    """POST /mode {'mode': 'online'} without Vertex AI creds returns informative message."""
    response = client.post("/mode", json={"mode": "online"})
    assert response.status_code == 200
    data = response.json()
    # Should not crash — should return status "error" with helpful message
    assert data["status"] in ("switched", "error")
    assert "mode" in data
    assert "message" in data


def test_mode_switch_invalid(client):
    """POST /mode with an invalid mode must return 422."""
    response = client.post("/mode", json={"mode": "turbo"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Memory stub
# ---------------------------------------------------------------------------

def test_memory_query_stub(client):
    """POST /memory/query returns empty list (Phase 4 stub)."""
    response = client.post("/memory/query", json={"query": "what do you know about me"})
    assert response.status_code == 200
    data = response.json()
    assert "facts" in data
    assert isinstance(data["facts"], list)
    assert len(data["facts"]) == 0  # Phase 4 stub always returns empty


# ---------------------------------------------------------------------------
# Screen stub
# ---------------------------------------------------------------------------

def test_screen_capture_stub(client):
    """POST /screen/capture returns a placeholder description."""
    response = client.post("/screen/capture")
    assert response.status_code == 200
    data = response.json()
    assert "description" in data
    assert "timestamp" in data
    assert len(data["description"]) > 0


# ---------------------------------------------------------------------------
# Control override
# ---------------------------------------------------------------------------

def test_control_override(client):
    """POST /control/override returns control_returned status."""
    response = client.post("/control/override")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "control_returned"
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Agents reload
# ---------------------------------------------------------------------------

def test_agents_reload(client):
    """POST /agents/reload returns reloaded status and correct agent count."""
    response = client.post("/agents/reload")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "reloaded"
    assert data["agents_loaded"] == 13
