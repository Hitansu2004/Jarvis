"""
Tests for memory_vault/correction_parser.py

These tests have NO external dependencies — no ChromaDB, no Graphiti, no Ollama.
They test pure Python logic. Run these first. They must all pass even with no
memory infrastructure installed.
"""

import pytest
from memory_vault.correction_parser import parse_correction_command, MemoryAction


# ── FORGET tests ──────────────────────────────────────────────────────────────

class TestForgetCommand:
    def test_basic_forget(self):
        action = parse_correction_command("Jarvis, forget that I use Tailwind CSS.")
        assert action.action_type == "FORGET"
        assert "tailwind" in action.entity.lower() or "css" in action.entity.lower()

    def test_forget_without_jarvis_prefix(self):
        action = parse_correction_command("forget that I prefer Redux")
        assert action.action_type == "FORGET"
        assert "redux" in action.entity.lower()

    def test_forget_framework(self):
        action = parse_correction_command("forget that I use Vue.js")
        assert action.action_type == "FORGET"

    def test_forget_high_confidence(self):
        action = parse_correction_command("forget that I use Bootstrap")
        assert action.confidence >= 0.9

    def test_forget_is_destructive(self):
        action = parse_correction_command("forget that I like Python")
        assert action.is_destructive is True


# ── REMEMBER tests ────────────────────────────────────────────────────────────

class TestRememberCommand:
    def test_basic_remember(self):
        action = parse_correction_command("Jarvis, remember that I now prefer TypeScript.")
        assert action.action_type == "REMEMBER"
        assert "typescript" in action.entity.lower()

    def test_remember_now_prefer(self):
        action = parse_correction_command("remember that I now prefer Zustand")
        assert action.action_type == "REMEMBER"

    def test_remember_is_not_destructive(self):
        action = parse_correction_command("remember that I prefer dark mode")
        assert action.is_destructive is False

    def test_remember_with_context(self):
        action = parse_correction_command("Jarvis, remember that I now use pnpm instead of npm")
        assert action.action_type == "REMEMBER"

    def test_remember_high_confidence(self):
        action = parse_correction_command("remember that I prefer AWS EC2")
        assert action.confidence >= 0.9


# ── SHOW PROFILE tests ────────────────────────────────────────────────────────

class TestShowProfileCommand:
    def test_what_do_you_know(self):
        action = parse_correction_command("Jarvis, what do you know about me?")
        assert action.action_type == "SHOW_PROFILE"

    def test_what_have_you_learned(self):
        action = parse_correction_command("what have you learned about me")
        assert action.action_type == "SHOW_PROFILE"

    def test_show_what_you_know(self):
        action = parse_correction_command("show me what you know about me")
        assert action.action_type == "SHOW_PROFILE"

    def test_profile_not_destructive(self):
        action = parse_correction_command("what do you know about me?")
        assert action.is_destructive is False


# ── SHOW WIKI tests ───────────────────────────────────────────────────────────

class TestShowWikiCommand:
    def test_show_coding_wiki(self):
        action = parse_correction_command("Jarvis, show me my coding wiki.")
        assert action.action_type == "SHOW_WIKI"
        assert action.wiki_file == "coding_style"

    def test_show_projects_wiki(self):
        action = parse_correction_command("show me my project wiki")
        assert action.action_type == "SHOW_WIKI"
        assert action.wiki_file == "projects"

    def test_show_shopping_wiki(self):
        action = parse_correction_command("show me my shopping wiki")
        assert action.action_type == "SHOW_WIKI"
        assert action.wiki_file == "shopping_patterns"

    def test_show_user_profile_wiki(self):
        action = parse_correction_command("show me my user profile wiki")
        assert action.action_type == "SHOW_WIKI"
        assert action.wiki_file == "user_profile"


# ── CLEAR DATE tests ──────────────────────────────────────────────────────────

class TestClearDateCommand:
    def test_clear_yesterday(self):
        action = parse_correction_command("Jarvis, clear everything you learned from yesterday")
        assert action.action_type == "CLEAR_DATE"
        assert action.target_date is not None
        assert action.is_destructive is True

    def test_clear_last_tuesday(self):
        action = parse_correction_command("clear everything from last Tuesday")
        assert action.action_type == "CLEAR_DATE"
        assert action.target_date is not None

    def test_clear_specific_day(self):
        action = parse_correction_command("clear everything you learned from Monday")
        assert action.action_type == "CLEAR_DATE"


# ── PAUSE LEARNING tests ──────────────────────────────────────────────────────

class TestPauseLearningCommand:
    def test_do_not_learn(self):
        action = parse_correction_command("Jarvis, do not learn from the next 10 minutes")
        assert action.action_type == "PAUSE_LEARNING"
        assert action.pause_minutes == 10

    def test_dont_learn(self):
        action = parse_correction_command("don't learn from the next 30 minutes")
        assert action.action_type == "PAUSE_LEARNING"
        assert action.pause_minutes == 30

    def test_pause_not_destructive(self):
        action = parse_correction_command("do not learn from the next 5 minutes")
        assert action.is_destructive is False


# ── UNKNOWN tests ─────────────────────────────────────────────────────────────

class TestUnknownCommand:
    def test_unrelated_message_is_unknown(self):
        action = parse_correction_command("What is the weather today?")
        assert action.action_type == "UNKNOWN"

    def test_unknown_has_low_confidence(self):
        action = parse_correction_command("hello jarvis how are you")
        assert action.action_type == "UNKNOWN"
        assert action.confidence < 0.5

    def test_unknown_not_destructive(self):
        action = parse_correction_command("just a random message")
        assert action.is_destructive is False
