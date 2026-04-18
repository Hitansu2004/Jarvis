"""
J.A.R.V.I.S. — tests/test_response_formats.py
Tests that JARVIS response formatting rules are correctly specified
in system prompts and core identity files.

Author: Hitansu Parichha | Nisum Technologies
Phase 3.5 — Response Architecture
"""
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# JARVIS_CORE.md tests
# ---------------------------------------------------------------------------

def test_jarvis_core_contains_response_taxonomy():
    """JARVIS_CORE.md must contain the response taxonomy section."""
    core = (PROJECT_ROOT / "JARVIS_CORE.md").read_text()
    assert "RESPONSE FORMAT TAXONOMY" in core

def test_jarvis_core_has_all_12_types():
    """All 12 response types must be defined in JARVIS_CORE.md."""
    core = (PROJECT_ROOT / "JARVIS_CORE.md").read_text()
    required_types = [
        "FACTUAL_SIMPLE", "FACTUAL_LIST", "OPINION_ANALYSIS", "COMPARISON",
        "CODE_WRITE", "CODE_EXPLAIN", "CODE_DEBUG", "TASK_CONFIRM",
        "RESEARCH_SUMMARY", "PLAN_STRATEGY", "CASUAL_CHAT", "SYSTEM_STATUS",
    ]
    for t in required_types:
        assert t in core, f"Response type '{t}' missing from JARVIS_CORE.md"

def test_jarvis_core_has_voice_mode_section():
    """JARVIS_CORE.md must contain voice mode formatting rules."""
    core = (PROJECT_ROOT / "JARVIS_CORE.md").read_text()
    assert "VOICE_MODE" in core
    assert "VOICE MODE" in core

def test_jarvis_core_has_anti_patterns():
    """JARVIS_CORE.md must list the anti-patterns."""
    core = (PROJECT_ROOT / "JARVIS_CORE.md").read_text()
    assert "ANTI-PATTERNS" in core or "ANTI-PATTERN" in core

def test_jarvis_core_has_wit_calibration():
    """JARVIS_CORE.md must contain wit calibration guide."""
    core = (PROJECT_ROOT / "JARVIS_CORE.md").read_text()
    assert "WIT" in core

def test_jarvis_core_has_no_cheerful_preamble():
    """JARVIS_CORE.md should explicitly forbid cheerful preambles."""
    core = (PROJECT_ROOT / "JARVIS_CORE.md").read_text()
    assert "Great question" in core  # Listed as anti-pattern
    assert "Certainly" in core  # Listed as anti-pattern

def test_jarvis_core_mentions_sir_limit():
    """JARVIS_CORE.md should note 'Sir' should be used at most twice."""
    core = (PROJECT_ROOT / "JARVIS_CORE.md").read_text()
    assert "twice" in core.lower() or "at most" in core.lower()

# ---------------------------------------------------------------------------
# Agent prompt tests
# ---------------------------------------------------------------------------

def test_all_agent_prompts_exist():
    """All 13 agent prompts must exist."""
    prompt_dir = PROJECT_ROOT / "prompts"
    required = [
        "receptionist.txt", "orchestrator.txt", "code_specialist.txt",
        "auditor.txt", "research.txt", "file_manager.txt",
        "browser_shopping.txt", "communication.txt", "system_control.txt",
        "screen_vision_passive.txt", "screen_vision_deep.txt",
        "memory_distiller.txt", "voice_triage.txt",
    ]
    for p in required:
        assert (prompt_dir / p).exists(), f"Missing prompt: {p}"

def test_code_specialist_has_no_cheerful_language():
    """Code specialist must not allow cheerful preambles."""
    prompt = (PROJECT_ROOT / "prompts" / "code_specialist.txt").read_text()
    # Should reference the anti-patterns
    assert "NEVER" in prompt

def test_code_specialist_has_voice_mode_rules():
    """Code specialist must have voice mode specific rules."""
    prompt = (PROJECT_ROOT / "prompts" / "code_specialist.txt").read_text()
    assert "VOICE" in prompt.upper()

def test_file_manager_has_double_confirmation():
    """File manager must explicitly require double confirmation for deletion."""
    prompt = (PROJECT_ROOT / "prompts" / "file_manager.txt").read_text()
    assert "double" in prompt.lower() or "second" in prompt.lower()
    assert "confirmation" in prompt.lower()

def test_auditor_has_confidence_levels():
    """Auditor must define confidence levels."""
    prompt = (PROJECT_ROOT / "prompts" / "auditor.txt").read_text()
    assert "HIGH" in prompt
    assert "MEDIUM" in prompt
    assert "LOW" in prompt

def test_communication_has_send_confirmation():
    """Communication agent must require confirmation before sending."""
    prompt = (PROJECT_ROOT / "prompts" / "communication.txt").read_text()
    assert "confirm" in prompt.lower()
    assert "send" in prompt.lower()

def test_voice_triage_outputs_json_only():
    """Voice triage must specify JSON output only."""
    prompt = (PROJECT_ROOT / "prompts" / "voice_triage.txt").read_text()
    assert "JSON" in prompt
    assert "intent" in prompt

def test_memory_distiller_outputs_json_only():
    """Memory distiller must specify JSON output only."""
    prompt = (PROJECT_ROOT / "prompts" / "memory_distiller.txt").read_text()
    assert "JSON" in prompt

def test_research_prompt_has_comparison_table():
    """Research prompt should define the comparison table format."""
    prompt = (PROJECT_ROOT / "prompts" / "research.txt").read_text()
    assert "table" in prompt.lower() or "|" in prompt

def test_receptionist_prompt_has_routing_examples():
    """Receptionist must have routing format examples."""
    prompt = (PROJECT_ROOT / "prompts" / "receptionist.txt").read_text()
    assert "developer environment" in prompt.lower() or "routing" in prompt.lower()

def test_browser_shopping_has_proactive_threshold():
    """Shopping agent must define when to proactively suggest alternatives."""
    prompt = (PROJECT_ROOT / "prompts" / "browser_shopping.txt").read_text()
    assert "15%" in prompt or "threshold" in prompt.lower() or "silence" in prompt.lower()

# ---------------------------------------------------------------------------
# Response architecture guide
# ---------------------------------------------------------------------------

def test_response_architecture_guide_exists():
    """prompts/response_architecture.md must exist."""
    assert (PROJECT_ROOT / "prompts" / "response_architecture.md").exists()

def test_response_architecture_guide_has_all_types():
    """Response architecture guide must document all 12 types."""
    guide = (PROJECT_ROOT / "prompts" / "response_architecture.md").read_text()
    required = [
        "FACTUAL_SIMPLE", "FACTUAL_LIST", "OPINION_ANALYSIS", "COMPARISON",
        "CODE_WRITE", "CODE_EXPLAIN", "CODE_DEBUG", "TASK_CONFIRM",
        "RESEARCH_SUMMARY", "PLAN_STRATEGY", "CASUAL_CHAT", "SYSTEM_STATUS",
    ]
    for t in required:
        assert t in guide, f"Type '{t}' missing from response_architecture.md"

# ---------------------------------------------------------------------------
# Infrastructure checks (gaps from Phase 3)
# ---------------------------------------------------------------------------

def test_requirements_has_sounddevice():
    """requirements.txt must include sounddevice."""
    req = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "sounddevice" in req

def test_requirements_has_soundfile():
    """requirements.txt must include soundfile."""
    req = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "soundfile" in req

def test_audio_output_gitkeep_exists():
    """voice_engine/audio_output/.gitkeep must exist."""
    gitkeep = PROJECT_ROOT / "voice_engine" / "audio_output" / ".gitkeep"
    assert gitkeep.exists(), "Missing .gitkeep in audio_output directory"

def test_gitignore_excludes_audio_files():
    """.gitignore must exclude WAV/MP3 files from audio_output."""
    gitignore = (PROJECT_ROOT / ".gitignore").read_text()
    assert "audio_output" in gitignore or "*.wav" in gitignore
