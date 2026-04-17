"""
J.A.R.V.I.S. — tests/test_wake_word.py
Phase 3 WakeWord tests using monkeypatching for CI safety.
"""

import sys
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def wwd(monkeypatch):
    monkeypatch.setenv("WAKE_WORD", "Hey Jarvis")
    
    # Mock openwakeword out so it uses simulation mode
    monkeypatch.setitem(sys.modules, 'openwakeword', None)
    monkeypatch.setitem(sys.modules, 'openwakeword.model', None)
    monkeypatch.setitem(sys.modules, 'sounddevice', None)
    
    from voice_engine.wake_word import WakeWordDetector
    
    detector = WakeWordDetector(callback=lambda: None)
    yield detector
    
    # Cleanup properly so thread doesn't hang the test suite
    if detector._running:
        detector.stop()

def test_wake_word_initializes_without_crash():
    from voice_engine.wake_word import WakeWordDetector
    d = WakeWordDetector(callback=lambda: None)
    assert d is not None
    assert d._running is False

def test_wake_word_read_from_env(monkeypatch):
    monkeypatch.setenv("WAKE_WORD", "Hey Jarvis")
    from voice_engine.wake_word import WakeWordDetector
    d = WakeWordDetector(callback=lambda: None)
    assert d.wake_word == "Hey Jarvis"

def test_callback_stored(wwd):
    def cb(): pass
    wwd.callback = cb
    assert wwd.callback is cb

def test_get_status_returns_all_keys(wwd):
    status = wwd.get_status()
    expected_keys = {
        "running", "oww_available", "mode", "wake_word",
        "detection_threshold", "cooldown_seconds"
    }
    assert expected_keys.issubset(status.keys())

def test_detector_not_running_at_init(wwd):
    assert wwd._running is False

def test_stop_when_not_started_doesnt_crash(wwd):
    # should not crash
    wwd.stop()

def test_simulation_mode_when_oww_unavailable(wwd):
    # We mocked openwakeword to be None
    wwd.start()
    assert wwd._oww_available is False
    assert wwd._running is True
    assert wwd._thread.name == "JarvisWakeWordSimulator"
    wwd.stop()

def test_detection_threshold_from_env(monkeypatch):
    monkeypatch.setenv("WAKE_WORD_THRESHOLD", "0.7")
    from voice_engine.wake_word import WakeWordDetector
    d = WakeWordDetector(callback=lambda: None)
    assert d._detection_threshold == 0.7
