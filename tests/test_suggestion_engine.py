import pytest
import time
from screen_engine.suggestion_engine import SuggestionEngine, get_suggestion_engine
from screen_engine.context_classifier import ScreenContext, CONTEXT_CODE_EDITING, CONTEXT_SHOPPING
from unittest.mock import MagicMock

@pytest.fixture
def base_context():
    return ScreenContext(
        app="other", context_type="other", is_shopping=False, is_coding=False,
        file_path="", current_line=0, language="", url="", site_name="",
        raw_context="", raw_description="", suggestions=[], timestamp=""
    )

def test_suggestion_engine_initializes():
    se = SuggestionEngine()
    assert se is not None

def test_should_suggest_false_when_suppressed(base_context):
    se = SuggestionEngine()
    se.suppress_for(300)
    assert se.should_suggest(base_context) is False

def test_should_suggest_false_within_cooldown(base_context):
    se = SuggestionEngine()
    se._last_suggestion_time = time.time()
    assert se.should_suggest(base_context) is False

def test_should_suggest_true_after_cooldown(base_context):
    se = SuggestionEngine()
    se._last_suggestion_time = time.time() - 200
    se._suppressed_until = 0
    assert se.should_suggest(base_context) is True

def test_should_suggest_code_requires_stability(base_context):
    se = SuggestionEngine()
    se._last_suggestion_time = 0
    se._suppressed_until = 0
    
    code_ctx = ScreenContext(
        app="vscode", context_type=CONTEXT_CODE_EDITING, is_shopping=False, is_coding=True,
        file_path="test.py", current_line=10, language="Python", url="", site_name="",
        raw_context="", raw_description="", suggestions=[], timestamp=""
    )
    
    assert se.should_suggest(code_ctx) is False
    assert se.should_suggest(code_ctx) is False
    assert se.should_suggest(code_ctx) is False
    assert se.should_suggest(code_ctx) is True

def test_suppress_for_sets_suppressed():
    se = SuggestionEngine()
    se.suppress_for(60)
    assert se.is_suppressed() is True

def test_suppression_expires():
    se = SuggestionEngine()
    se._suppressed_until = time.time() - 1
    assert se.is_suppressed() is False

def test_generate_suggestion_uses_vision_suggestion(base_context):
    se = SuggestionEngine()
    base_context.suggestions = ["Add error handling to async function"]
    res = se.generate_suggestion(base_context)
    assert "error handling" in res

def test_generate_suggestion_jarvis_format(base_context):
    se = SuggestionEngine()
    base_context.suggestions = ["Fix typo"]
    res = se.generate_suggestion(base_context)
    assert res.startswith("Sorry to interrupt, Sir.")

def test_generate_suggestion_shopping_fallback():
    se = SuggestionEngine()
    ctx = ScreenContext("browser", CONTEXT_SHOPPING, True, False, "", 0, "", "", "amazon", "", "", [], "")
    res = se.generate_suggestion(ctx)
    assert res is not None
    assert "Sorry to interrupt" in res

def test_record_suggestion_delivered_resets_cooldown():
    se = SuggestionEngine()
    se._last_suggestion_time = 0.0
    se.record_suggestion_delivered()
    assert se._last_suggestion_time > 0.0

def test_get_status_returns_complete_dict():
    se = SuggestionEngine()
    status = se.get_status()
    assert "suppressed" in status
    assert "cooldown_seconds" in status
    assert "cooldown_remaining_seconds" in status
    assert "observations_since_last_suggestion" in status
