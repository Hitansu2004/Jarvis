"""
J.A.R.V.I.S. — tests/test_tts_engine.py
Phase 3 TTSEngine tests using monkeypatching for CI safety.
"""

import sys
import os
import pytest
import asyncio
from unittest.mock import MagicMock

# Create dummy modules in sys.modules so the engine handles ImportErrors gracefully 
# during tests without invoking real models.

@pytest.fixture
def tts_engine(monkeypatch, tmp_path):
    # Mock environment variables
    monkeypatch.setenv("TTS_VOICE_REF_FILE", str(tmp_path / "jarvis_ref.wav"))
    monkeypatch.setenv("TTS_VOICE_REF_TEXT", "Test ref text.")
    
    # Mock libraries to be absent, triggering graceful fallbacks.
    monkeypatch.setitem(sys.modules, 'kokoro_onnx', None)
    monkeypatch.setitem(sys.modules, 'sounddevice', None)
    
    from voice_engine.tts import TTSEngine
    # Instantiate cleanly
    return TTSEngine()

def test_tts_engine_initializes_without_crash(tts_engine):
    assert tts_engine is not None

def test_get_status_returns_all_keys(tts_engine):
    status = tts_engine.get_status()
    expected_keys = {
        "active_engine", "kokoro_available", "voice_en", "voice_hi", "speed"
    }
    assert expected_keys.issubset(status.keys())



def test_split_sentences_single_sentence(tts_engine):
    sentences = tts_engine._split_sentences("Hello, Sir.")
    assert sentences == ["Hello, Sir."]

def test_split_sentences_multiple(tts_engine):
    sentences = tts_engine._split_sentences("Hello, Sir. How are you? I am fine.")
    assert len(sentences) == 3

def test_split_sentences_filters_empty(tts_engine):
    assert tts_engine._split_sentences("  ") == []

@pytest.mark.asyncio
async def test_speak_console_fallback(tts_engine, capsys):
    # Ensure all are false
    tts_engine._f5tts_available = False
    tts_engine._kokoro_available = False
    tts_engine._chatterbox_available = False
    
    result = await tts_engine.speak("Test fallback.")
    assert result is True
    
    captured = capsys.readouterr()
    assert "[JARVIS]: Test fallback." in captured.out

@pytest.mark.asyncio
async def test_speak_empty_text_returns_false(tts_engine):
    assert await tts_engine.speak("") is False
    assert await tts_engine.speak("   ") is False

@pytest.mark.asyncio
async def test_speak_bridging_phrase_code(tts_engine, capsys):
    await tts_engine.speak_bridging_phrase("code")
    captured = capsys.readouterr()
    assert "Working on it" in captured.out

@pytest.mark.asyncio
async def test_speak_bridging_phrase_unknown_key(tts_engine, capsys):
    result = await tts_engine.speak_bridging_phrase("unknown_task")
    # Returns None but shouldn't crash.
    captured = capsys.readouterr()
    assert "One moment, Sir" in captured.out

def test_audio_output_dir_created(tts_engine):
    assert tts_engine._audio_output_dir.exists()
    assert tts_engine._audio_output_dir.is_dir()
