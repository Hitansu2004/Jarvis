"""
J.A.R.V.I.S. — tests/test_phase3_integration.py
Phase 3 FastAPI integration tests for the /voice/* suite.
"""

import pytest
import sys
from fastapi.testclient import TestClient

# Mock all voice libraries before importing the gateway
import pytest
@pytest.fixture(autouse=True, scope="session")
def mock_voice_deps():
    import sys
    sys.modules['kokoro_onnx'] = None
    sys.modules['f5_tts'] = None
    sys.modules['f5_tts.api'] = None
    sys.modules['chatterbox'] = None
    sys.modules['chatterbox.tts'] = None
    sys.modules['sounddevice'] = None
    sys.modules['whisper'] = None
    sys.modules['openwakeword'] = None
    sys.modules['openwakeword.model'] = None

from core_engine.gateway import app

@pytest.fixture(scope="module")
def test_client():
    with TestClient(app) as c:
        yield c

def test_voice_status_endpoint(test_client):
    response = test_client.get("/voice/status")
    assert response.status_code == 200
    expected_keys = {"state", "tts", "stt", "wake_word"}
    assert expected_keys.issubset(response.json().keys())

def test_voice_speak_endpoint_console_fallback(test_client):
    response = test_client.post("/voice/speak", json={"text": "Hello Sir", "urgent": True})
    assert response.status_code == 200
    data = response.json()
    assert "spoken" in data
    assert data["text"] == "Hello Sir"

def test_voice_speak_empty_text_returns_error(test_client):
    response = test_client.post("/voice/speak", json={"text": ""})
    assert response.status_code == 422

def test_voice_listen_endpoint_stub(test_client):
    response = test_client.post("/voice/listen", json={"duration_seconds": 0.1})
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert "language_detected" in data
    # Will be empty text due to no sounddevice in mocked env.

def test_voice_wake_endpoint(test_client):
    response = test_client.post("/voice/wake")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "wake_triggered"
    assert "session_id" in data

def test_voice_suppress_endpoint(test_client):
    response = test_client.post("/voice/suppress", json={"seconds": 30})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "suppressed"
    assert data["seconds"] == 30

def test_voice_suppressed_suggestions_endpoint(test_client):
    response = test_client.get("/voice/suppressed")
    assert response.status_code == 200
    data = response.json()
    assert "suggestions" in data
    assert "count" in data

def test_chat_with_speak_param(test_client, monkeypatch):
    """POST /chat?speak=true must return 200 with a valid response schema."""
    from core_engine import gateway as gw
    from core_engine.mode_manager import ModeManager

    async def mock_complete(*args, **kwargs):
        return {
            "content": "This is a mocked response, Sir.",
            "model_used": "mock",
            "mode": "offline",
            "tokens_in": 5,
            "tokens_out": 8,
        }

    # Patch both the class AND the live singleton instance
    monkeypatch.setattr(ModeManager, "complete", mock_complete)
    if gw._mode_manager:
        monkeypatch.setattr(gw._mode_manager, "complete", mock_complete)

    response = test_client.post("/chat?speak=true", json={"message": "hello"})
    assert response.status_code == 200
    data = response.json()
    # Verify schema is correct — not the exact LLM content
    assert "response" in data
    assert "agent_used" in data
    assert "model_used" in data
    assert "complexity_score" in data
    assert "mode" in data
    assert len(data["response"]) > 0
    assert isinstance(data["complexity_score"], int)

def test_all_phase1_phase2_routes_still_work(test_client):
    assert test_client.get("/health").status_code == 200
    assert test_client.get("/status").status_code == 200
    assert test_client.get("/agents").status_code == 200
    
    # Mock Vertex validation for mode switch
    from core_engine.mode_manager import ModeManager
    from sandbox.security_enforcer import SecurityEnforcer
    ModeManager.validate_mode_switch = lambda self, target: {"valid": True}
    
    # We must also mock security manager's HTTP requirement check
    response = test_client.post("/mode", json={"mode": "offline"})
    assert response.status_code == 200

    assert test_client.get("/security/status").status_code == 200
    assert test_client.get("/security/audit").status_code == 200

    assert response.status_code == 200
    data = response.json()

