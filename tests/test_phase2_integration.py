"""
J.A.R.V.I.S. — tests/test_phase2_integration.py
End-to-end integration tests using FastAPI TestClient to hit the new 
Phase 2 security endpoints on the gateway.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core_engine.gateway import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Provide a TestClient for testing FastAPI routes."""
    # Using 'with TestClient(app) as client' triggers lifespan events (startup/shutdown)
    with TestClient(app) as c:
        yield c


def test_security_status_endpoint(client: TestClient):
    """GET /security/status should return 200 with complete dict."""
    response = client.get("/security/status")
    assert response.status_code == 200
    data = response.json()
    assert "path_guard_active" in data
    assert "network_guard_active" in data
    assert "audit_chain_valid" in data
    assert "pending_confirmations" in data


def test_security_audit_endpoint(client: TestClient):
    """GET /security/audit should return 200 and recent entries."""
    response = client.get("/security/audit")
    assert response.status_code == 200
    data = response.json()
    assert "entries" in data
    assert "total" in data
    assert isinstance(data["entries"], list)


def test_security_violations_endpoint(client: TestClient):
    """GET /security/violations should return 200."""
    response = client.get("/security/violations")
    assert response.status_code == 200
    data = response.json()
    assert "violations" in data
    assert "count" in data


def test_confirm_endpoint_invalid_key(client: TestClient):
    """POST /security/confirm with bad key returns status='not_found'."""
    response = client.post("/security/confirm", json={"confirmation_key": "fake-key-xyz"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found"


def test_cancel_endpoint_invalid_key(client: TestClient):
    """POST /security/cancel with bad key returns status='not_found'."""
    response = client.post("/security/cancel", json={"confirmation_key": "fake-key-xyz"})
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


def test_audit_contains_startup_entry(client: TestClient):
    """Lifespan should have logged STARTUP."""
    response = client.get("/security/audit")
    assert response.status_code == 200
    entries = response.json()["entries"]
    
    # Check if any entry in the recent ones is a STARTUP
    has_startup = any(e.get("action_type") == "STARTUP" for e in entries)
    assert has_startup


def test_chat_request_appears_in_audit(client: TestClient, monkeypatch):
    """A POST to /chat logs to audit."""
    import core_engine.gateway as gw_module
    
    # Monkeypatch the mode manager complete to avoid actually calling LLMs
    async def mock_complete(*args, **kwargs):
        return {
            "content": "Mocked response",
            "model_used": "mocked_model",
            "mode": "offline",
        }
    
    monkeypatch.setattr(gw_module._mode_manager, "complete", mock_complete)
    
    # Send a chat request
    chat_resp = client.post("/chat", json={"message": "hello jarvis"})
    assert chat_resp.status_code == 200
    
    # Check audit log for CHAT
    audit_resp = client.get("/security/audit?limit=10")
    entries = audit_resp.json()["entries"]
    
    has_chat = any(e.get("action_type") == "CHAT" for e in entries)
    assert has_chat


def test_security_status_shows_path_guard_active(client: TestClient):
    """PathGuard is active in the status report."""
    response = client.get("/security/status")
    assert response.json()["path_guard_active"] is True


def test_security_status_shows_network_guard_active(client: TestClient):
    """NetworkGuard is active in the status report."""
    response = client.get("/security/status")
    assert response.json()["network_guard_active"] is True
