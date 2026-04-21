import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from screen_engine.vision import ScreenVision, get_screen_vision

def test_screen_vision_initializes_without_crash():
    sv = ScreenVision()
    assert sv is not None

@patch('builtins.__import__')
def test_mss_available_flag_set(mock_import):
    import sys
    sys.modules['mss'] = MagicMock()
    sv = ScreenVision()
    assert sv._mss_available is True

@patch('screen_engine.vision.ScreenVision.capture_screenshot', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_capture_screenshot_returns_bytes(mock_capture):
    mock_capture.return_value = b'fake_png_bytes'
    sv = ScreenVision()
    bytes = await sv.capture_screenshot()
    assert bytes == b'fake_png_bytes'

@pytest.mark.asyncio
async def test_capture_screenshot_handles_mss_missing():
    sv = ScreenVision()
    sv._mss_available = False
    bytes = await sv.capture_screenshot()
    assert bytes == b""

@patch('screen_engine.vision.ScreenVision.capture_screenshot', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_capture_and_describe_without_mode_manager(mock_capture):
    mock_capture.return_value = b'bytes'
    sv = ScreenVision()
    sv._mss_available = True
    res = await sv.capture_and_describe(deep=False, mode_manager=None)
    assert all(k in res for k in ['description', 'app_detected', 'context', 'suggestions', 'timestamp', 'screenshot_b64', 'deep', 'model_used'])

@patch('screen_engine.vision.ScreenVision.capture_screenshot', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_capture_and_describe_without_mss(mock_capture):
    mock_capture.return_value = b''
    sv = ScreenVision()
    sv._mss_available = False
    res = await sv.capture_and_describe(deep=False, mode_manager=None)
    assert "unavailable" in res['description']
    assert res['model_used'] == 'none'

@patch('screen_engine.vision.ScreenVision.capture_screenshot', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_capture_and_describe_with_mock_mode_manager(mock_capture):
    mock_capture.return_value = b'img'
    mock_mm = MagicMock()
    mock_mm.complete = AsyncMock(return_value={
        "content": """APP: vscode
CONTEXT: auth.ts line 26
DESCRIPTION: User editing TypeScript file.
SUGGESTION: Add error handling to async function.""",
        "model_used": "gemma4:e4b"
    })
    mock_ar = MagicMock()
    mock_ar.get_system_prompt.return_value = "prompt"
    
    sv = ScreenVision()
    sv._mss_available = True
    res = await sv.capture_and_describe(deep=False, mode_manager=mock_mm, agent_registry=mock_ar)
    assert res['app_detected'] == 'vscode'
    assert len(res['suggestions']) > 0

def test_parse_vision_response_vscode():
    sv = ScreenVision()
    res = sv._parse_vision_response("""APP: vscode
CONTEXT: auth.ts
DESCRIPTION: Editing.
SUGGESTION: none""")
    assert res['app'] == 'vscode'
    assert res['suggestion'] == 'none'

def test_parse_vision_response_browser_shopping():
    sv = ScreenVision()
    res = sv._parse_vision_response("""APP: browser
CONTEXT: flipkart.com
DESCRIPTION: Shopping.
SUGGESTION: Search for alternatives.""")
    assert res['app'] == 'browser'
    assert 'alternatives' in res['suggestion']

def test_parse_vision_response_handles_partial():
    sv = ScreenVision()
    res = sv._parse_vision_response("Just a plain text response without format")
    assert all(k in res for k in ['app', 'context', 'description', 'suggestion'])

@patch('screen_engine.vision.ScreenVision.capture_screenshot', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_deep_mode_uses_different_agent(mock_capture):
    mock_capture.return_value = b'img'
    mock_mm = MagicMock()
    mock_mm.complete = AsyncMock(return_value={"content": "", "model_used": "gemma4:26b"})
    
    sv = ScreenVision()
    sv._mss_available = True
    await sv.capture_and_describe(deep=True, mode_manager=mock_mm, agent_registry=MagicMock())
    mock_mm.complete.assert_called_once()
    assert mock_mm.complete.call_args[1]['agent_name'] == "screen_vision_deep"

def test_get_screen_vision_returns_singleton():
    a = get_screen_vision()
    b = get_screen_vision()
    assert a is b
