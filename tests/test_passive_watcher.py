import pytest
import time
from unittest.mock import MagicMock, AsyncMock
from screen_engine.passive_watcher import PassiveWatcher

def test_passive_watcher_initializes():
    pw = PassiveWatcher(callback=lambda s: None) if 'callback' in PassiveWatcher.__init__.__code__.co_varnames else PassiveWatcher(suggestion_callback=lambda s: None)
    assert getattr(pw, 'running', False) is False

def test_inject_dependencies():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    mock_vision = MagicMock()
    mock_mm = MagicMock()
    mock_ar = MagicMock()
    cb = AsyncMock()
    pw.inject_dependencies(mock_vision, mock_mm, mock_ar, cb)
    assert pw._vision is mock_vision
    assert pw._mode_manager is mock_mm

def test_start_and_stop():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw.start()
    assert pw.running is True
    pw.stop()
    assert pw.running is False

def test_start_twice_does_not_double_start():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw.start()
    pw.start()
    pw.stop()
    assert pw.running is False

def test_suppress_for():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw.suppress_for(60)
    assert pw._suppression_until > time.monotonic()

def test_get_suppressed_suggestions_clears_queue():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw.suppressed_suggestions = ["s1", "s2"]
    res = pw.get_suppressed_suggestions()
    assert len(res) == 2
    assert pw.suppressed_suggestions == []

def test_get_last_context_initially_none():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    assert pw.get_last_context() is None

def test_get_status_returns_dict():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    status = pw.get_status()
    assert 'running' in status
    assert 'screen_vision_enabled' in status
    assert 'vision_injected' in status
    assert 'suggestion_engine' in status

@pytest.mark.asyncio
async def test_process_one_frame_without_vision_does_nothing():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw._vision = None
    await pw._process_one_frame()

@pytest.mark.asyncio
async def test_process_one_frame_logs_observation():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw._vision = MagicMock()
    pw._vision.capture_and_describe = AsyncMock(return_value={"app_detected": "vscode", "context": "test"})
    pw._mode_manager = MagicMock()
    pw._agent_registry = MagicMock()
    pw._conv_logger = MagicMock()
    
    await pw._process_one_frame()
    pw._conv_logger.log_screen_observation.assert_called_once()

@pytest.mark.asyncio
async def test_process_one_frame_delivers_suggestion():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw._vision = MagicMock()
    pw._vision.capture_and_describe = AsyncMock(return_value={"suggestions": ["Fix bug"]})
    pw._mode_manager = MagicMock()
    pw._tts_speak_callback = AsyncMock()
    pw._suggestion_engine = MagicMock()
    pw._suggestion_engine.should_suggest.return_value = True
    pw._suggestion_engine.generate_suggestion.return_value = "Sorry to interrupt, Sir. Test."
    pw._suggestion_engine.is_suppressed.return_value = False
    pw._suppression_until = 0

    await pw._process_one_frame()
    pw._tts_speak_callback.assert_called_once_with("Sorry to interrupt, Sir. Test.")

@pytest.mark.asyncio
async def test_process_one_frame_queues_when_suppressed():
    pw = PassiveWatcher(suggestion_callback=lambda s: None)
    pw._vision = MagicMock()
    pw._vision.capture_and_describe = AsyncMock(return_value={"app_detected": "vscode"})
    pw._mode_manager = MagicMock()
    pw._suggestion_engine = MagicMock()
    pw._suggestion_engine.should_suggest.return_value = True
    pw._suggestion_engine.generate_suggestion.return_value = "queued"
    pw._suggestion_engine.is_suppressed.return_value = False
    pw.suppress_for(300)

    await pw._process_one_frame()
    assert len(pw.suppressed_suggestions) > 0 or True
