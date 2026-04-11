"""
J.A.R.V.I.S. — tests/test_router.py
ComplexityRouter classification tests.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

import os
import pytest

from core_engine.router import ComplexityRouter


@pytest.fixture
def router():
    """Return a fresh ComplexityRouter instance."""
    return ComplexityRouter()


# ---------------------------------------------------------------------------
# Score range tests
# ---------------------------------------------------------------------------

def test_simple_greeting_scores_low(router):
    """'hello' should score 1-2 (LIGHT)."""
    result = router.classify("hello")
    assert 1 <= result["score"] <= 4, f"Expected 1-4, got {result['score']}"
    assert result["tier"] == "light"


def test_hi_greeting_scores_low(router):
    """'hi' should score in the light range."""
    result = router.classify("hi")
    assert result["score"] <= 4


def test_status_query_scores_low(router):
    """'what mode are you in' should score 1-2."""
    result = router.classify("what mode are you in")
    assert 1 <= result["score"] <= 4, f"Expected 1-4, got {result['score']}"


def test_code_request_scores_high(router):
    """'write a Python function to sort a list' should score 7-8."""
    result = router.classify("write a Python function to sort a list")
    assert result["score"] >= 7, f"Expected >= 7, got {result['score']}"
    assert result["tier"] in ("medium", "complex")


def test_complex_research_scores_medium(router):
    """'research the best tablets under 30000 rupees' should score 5-6."""
    result = router.classify("research the best tablets under 30000 rupees")
    assert result["score"] >= 5, f"Expected >= 5, got {result['score']}"


def test_multi_step_scores_high(router):
    """'research and then implement a REST API for user auth' should score 9-10."""
    result = router.classify("research and then implement a REST API for user auth")
    assert result["score"] >= 7, f"Expected >= 7, got {result['score']}"


def test_debug_keyword_scores_high(router):
    """Message containing 'debug' should score in the high range."""
    result = router.classify("can you debug this error in my code")
    assert result["score"] >= 7, f"Expected >= 7, got {result['score']}"


def test_very_long_message_scores_high(router):
    """A message with > 200 words should score 9."""
    long_msg = " ".join(["word"] * 210)
    result = router.classify(long_msg)
    assert result["score"] >= 9, f"Expected >= 9 for 210-word message, got {result['score']}"


# ---------------------------------------------------------------------------
# Return structure tests
# ---------------------------------------------------------------------------

def test_returns_agent_recommendation(router):
    """Every classification must include 'recommended_agent' key."""
    result = router.classify("hello")
    assert "recommended_agent" in result
    assert isinstance(result["recommended_agent"], str)
    assert len(result["recommended_agent"]) > 0


def test_returns_tier(router):
    """'tier' must be one of 'light', 'medium', 'complex'."""
    result = router.classify("hello")
    assert "tier" in result
    assert result["tier"] in ("light", "medium", "complex")


def test_returns_reasoning(router):
    """Every classification must include a non-empty 'reasoning' string."""
    result = router.classify("write a function")
    assert "reasoning" in result
    assert len(result["reasoning"]) > 0


def test_empty_message_returns_light(router):
    """Empty message should return light score without crashing."""
    result = router.classify("")
    assert result["score"] == 1
    assert result["tier"] == "light"


# ---------------------------------------------------------------------------
# Agent mapping tests
# ---------------------------------------------------------------------------

def test_light_message_uses_receptionist(router):
    """Light messages (score 1-4) should recommend 'receptionist'."""
    result = router.classify("hi")
    assert result["recommended_agent"] == "receptionist"


def test_code_message_uses_code_specialist(router):
    """Code messages should recommend 'code_specialist'."""
    result = router.classify("write a Python class with error handling")
    assert result["recommended_agent"] == "code_specialist"


# ---------------------------------------------------------------------------
# Model selection tests
# ---------------------------------------------------------------------------

def test_offline_model_prototype_mode(monkeypatch):
    """When PROTOTYPE_MODE=true, get_offline_model always returns gemma4:e4b."""
    monkeypatch.setenv("PROTOTYPE_MODE", "true")
    monkeypatch.setenv("MODEL_RECEPTIONIST", "gemma4:e4b")
    router = ComplexityRouter()
    assert router.get_offline_model("code_specialist", 9) == "gemma4:e4b"
    assert router.get_offline_model("orchestrator", 7) == "gemma4:e4b"


def test_offline_model_normal_mode(monkeypatch):
    """In normal mode, code_specialist should get gemma4:26b."""
    monkeypatch.setenv("PROTOTYPE_MODE", "false")
    monkeypatch.setenv("MODEL_SPECIALIST_CODE", "gemma4:26b")
    router = ComplexityRouter()
    model = router.get_offline_model("code_specialist", 8)
    assert model == "gemma4:26b"


def test_online_model_high_complexity(monkeypatch):
    """Score 9 should return MODEL_ONLINE_COMPLEX."""
    monkeypatch.setenv("MODEL_ONLINE_COMPLEX", "gemini-2.5-pro")
    monkeypatch.setenv("COMPLEXITY_VERTEX_PRO", "8")
    router = ComplexityRouter()
    assert router.get_online_model(9) == "gemini-2.5-pro"


def test_online_model_medium_complexity(monkeypatch):
    """Score 6 should return MODEL_ONLINE_MEDIUM."""
    monkeypatch.setenv("MODEL_ONLINE_MEDIUM", "gemini-2.5-flash")
    monkeypatch.setenv("COMPLEXITY_VERTEX_PRO", "8")
    monkeypatch.setenv("COMPLEXITY_VERTEX_FLASH", "5")
    router = ComplexityRouter()
    assert router.get_online_model(6) == "gemini-2.5-flash"


def test_online_model_low_complexity(monkeypatch):
    """Score 2 should return MODEL_ONLINE_LIGHT."""
    monkeypatch.setenv("MODEL_ONLINE_LIGHT", "gemini-2.5-flash-lite")
    monkeypatch.setenv("COMPLEXITY_VERTEX_PRO", "8")
    monkeypatch.setenv("COMPLEXITY_VERTEX_FLASH", "5")
    router = ComplexityRouter()
    assert router.get_online_model(2) == "gemini-2.5-flash-lite"
