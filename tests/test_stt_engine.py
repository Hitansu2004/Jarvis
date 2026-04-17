"""
J.A.R.V.I.S. — tests/test_stt_engine.py
Phase 3 STTEngine tests using monkeypatching for CI safety.
"""

import sys
import os
import pytest
import numpy as np
from unittest.mock import MagicMock

@pytest.fixture
def stt_engine(monkeypatch, tmp_path):
    # Mock environment variables
    monkeypatch.setenv("STT_MODEL", "whisper-small")
    monkeypatch.setenv("STT_DEVICE", "mps")
    
    # Mock libraries to be absent initially
    monkeypatch.setitem(sys.modules, 'whisper', None)
    monkeypatch.setitem(sys.modules, 'sounddevice', None)
    
    from voice_engine.stt import STTEngine
    stt = STTEngine()
    # Explicitly set unavailable for base tests to ensure no real model loads
    stt._whisper_available = False
    return stt

def test_stt_engine_initializes_without_crash(stt_engine):
    assert stt_engine is not None
    assert stt_engine._model is None

def test_model_not_loaded_at_init(stt_engine):
    assert stt_engine._model is None
    assert stt_engine._whisper_available is False

def test_get_status_returns_all_keys(stt_engine):
    status = stt_engine.get_status()
    expected_keys = {
        "whisper_available", "model_name", "device",
        "model_loaded", "sample_rate"
    }
    assert expected_keys.issubset(status.keys())

@pytest.mark.asyncio
async def test_transcribe_returns_empty_when_unavailable(stt_engine):
    stt_engine._whisper_available = False
    stt_engine._is_loading = True # trick it into returning false from _ensure_loaded
    
    result = await stt_engine.transcribe(np.zeros(16000))
    assert result == ""

@pytest.mark.asyncio
async def test_transcribe_file_returns_empty_when_unavailable(stt_engine):
    stt_engine._whisper_available = False
    stt_engine._is_loading = True
    assert await stt_engine.transcribe_file("dummy.wav") == ""

def test_model_name_strips_whisper_prefix(monkeypatch):
    monkeypatch.setenv("STT_MODEL", "whisper-small")
    from voice_engine.stt import STTEngine
    stt = STTEngine()
    assert stt.model_name == "small"

def test_model_name_works_without_prefix(monkeypatch):
    monkeypatch.setenv("STT_MODEL", "small")
    from voice_engine.stt import STTEngine
    stt = STTEngine()
    assert stt.model_name == "small"

def test_device_defaults_to_mps(monkeypatch):
    monkeypatch.delenv("STT_DEVICE", raising=False)
    from voice_engine.stt import STTEngine
    stt = STTEngine()
    assert stt.device == "mps"

@pytest.mark.asyncio
async def test_transcribe_with_mock_model(stt_engine):
    # Setup mock whisper model
    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"text": "Hello sir"}
    
    stt_engine._model = mock_model
    stt_engine._whisper_available = True
    
    result = await stt_engine.transcribe(np.zeros(16000))
    assert result == "Hello sir"
    mock_model.transcribe.assert_called_once()

@pytest.mark.asyncio
async def test_record_and_transcribe_without_sounddevice(stt_engine):
    # _whisper_available is false, sounddevice mock is None
    result = await stt_engine.record_and_transcribe()
    assert result == ""
