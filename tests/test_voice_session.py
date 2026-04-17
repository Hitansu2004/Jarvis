"""
J.A.R.V.I.S. — tests/test_voice_session.py
Phase 3 test simulating the Voice Session workflow.
"""

import pytest
import time
import sys
from unittest.mock import MagicMock

# Create stubs for the three engines so they won't initialize the full hardware stack.
@pytest.fixture
def vsm(monkeypatch):
    monkeypatch.setitem(sys.modules, 'kokoro_onnx', None)
    monkeypatch.setitem(sys.modules, 'f5_tts', None)
    monkeypatch.setitem(sys.modules, 'f5_tts.api', None)
    monkeypatch.setitem(sys.modules, 'chatterbox', None)
    monkeypatch.setitem(sys.modules, 'chatterbox.tts', None)
    monkeypatch.setitem(sys.modules, 'sounddevice', None)
    monkeypatch.setitem(sys.modules, 'whisper', None)
    monkeypatch.setitem(sys.modules, 'openwakeword', None)
    monkeypatch.setitem(sys.modules, 'openwakeword.model', None)
    
    from voice_engine.voice_session import VoiceSessionManager
    manager = VoiceSessionManager()
    return manager

def test_voice_session_initializes(vsm):
    assert vsm is not None

def test_initial_state_is_idle(vsm):
    assert vsm._state == "idle"

def test_get_status_returns_complete_dict(vsm):
    status = vsm.get_status()
    expected_keys = {
        "state", "tts", "stt", "wake_word", 
        "suggestion_suppressed", "suppressed_suggestion_count"
    }
    assert expected_keys.issubset(status.keys())

def test_suppress_suggestions(vsm):
    vsm.suppress_suggestions(60)
    assert vsm.is_suggestion_suppressed() is True

def test_suppress_expires(vsm):
    vsm.suppress_suggestions(0)
    time.sleep(0.01)
    assert vsm.is_suggestion_suppressed() is False

def test_queue_suppressed_suggestion(vsm):
    vsm.suppress_suggestions(100)
    vsm.queue_suppressed_suggestion("I noticed a bug, Sir.")
    suggestions = vsm.get_suppressed_suggestions()
    assert "I noticed a bug, Sir." in suggestions

def test_get_suppressed_clears_queue(vsm):
    vsm.queue_suppressed_suggestion("test")
    vsm.get_suppressed_suggestions()
    assert len(vsm.get_suppressed_suggestions()) == 0

@pytest.mark.asyncio
async def test_speak_response_calls_tts(vsm):
    # Mock TTS speak logic
    async def mock_speak(text, language="en", urgent=False):
        return True
    
    vsm._tts.speak = mock_speak
    result = await vsm.speak_response("Hello, Sir.")
    assert result is True

def test_set_transcription_callback(vsm):
    called = []
    vsm.set_transcription_callback(lambda t, s: called.append(t))
    assert vsm._on_transcription_callback is not None
