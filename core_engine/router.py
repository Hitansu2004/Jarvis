"""
J.A.R.V.I.S. — core_engine/router.py
Complexity Classifier — assigns a score of 1-10 to every incoming message
and determines which agent and model tier to use.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyword banks for rule-based scoring
# ---------------------------------------------------------------------------

_LIGHT_GREETINGS = {
    "hello", "hi", "hey", "howdy", "good morning", "good afternoon",
    "good evening", "greetings", "what time is it", "how are you",
    "what mode are you in", "are you online", "are you offline",
    "switch to online", "go offline", "go online", "switch to offline",
    "yes", "no", "ok", "okay", "sure", "nope", "yep",
}

_LIGHT_MEDIUM_PATTERNS = [
    r"\bwhat do you know about\b",
    r"\bwhat did i say\b",
    r"\bweather\b",
    r"\bcalendar\b",
    r"\breminder\b",
    r"\bwhat is\b",
    r"\bwho is\b",
    r"\btell me about\b",
    r"\bdefine\b",
]

_CODE_KEYWORDS = {
    "code", "function", "class", "bug", "debug", "refactor", "implement",
    "write a", "write the", "fix this", "fix the", "error", "exception",
    "algorithm", "api", "endpoint", "database", "query", "test", "deploy",
    "unittest", "pytest", "async", "await", "import", "module", "package",
    "compile", "build", "lint", "syntax", "type hint", "dataclass",
    "decorator", "lambda", "generator", "iterator", "context manager",
    "git", "commit", "branch", "merge", "pull request", "dockerfile",
    "kubernetes", "terraform", "aws", "gcp", "azure", "ci/cd", "pipeline",
}

_MEDIUM_KEYWORDS = {
    "plan", "organize", "summarize", "summary", "research", "find best",
    "compare", "email", "slack", "jira", "notion", "file", "organize",
    "shopping", "buy", "price", "product", "schedule", "meeting",
    "what are the", "explain", "how does", "why does",
}

_VERY_COMPLEX_MULTI = [
    r"research.*and.*implement",
    r"research.*and.*deploy",
    r"implement.*and.*deploy",
    r"build.*and.*test.*and",
    r"design.*architecture",
    r"codebase.*analysis",
    r"multiple.*agents",
    r"end.to.end",
]

# ---------------------------------------------------------------------------
# Agent → tier mapping
# ---------------------------------------------------------------------------

_AGENT_MAP = {
    (1, 4): "receptionist",
    (5, 6): "orchestrator",
    (7, 8): "code_specialist",
    (9, 10): "orchestrator",  # orchestrator will sub-delegate
}

_TIER_MAP = {
    (1, 4): "light",
    (5, 7): "medium",
    (8, 10): "complex",
}


def _score_to_agent(score: int) -> str:
    """Return recommended agent name for a given complexity score."""
    for (lo, hi), agent in _AGENT_MAP.items():
        if lo <= score <= hi:
            return agent
    return "receptionist"


def _score_to_tier(score: int) -> str:
    """Return tier label for a given complexity score."""
    for (lo, hi), tier in _TIER_MAP.items():
        if lo <= score <= hi:
            return tier
    return "light"


# ---------------------------------------------------------------------------
# ComplexityRouter
# ---------------------------------------------------------------------------

class ComplexityRouter:
    """
    Rule-based complexity classifier with LLM fallback.

    Assigns every incoming message a score of 1-10 and recommends
    the appropriate JARVIS agent and model tier.
    """

    def __init__(self) -> None:
        """Initialise the router, loading env-based thresholds."""
        self.complexity_threshold = int(os.getenv("COMPLEXITY_THRESHOLD", "7"))
        self.prototype_mode = os.getenv("PROTOTYPE_MODE", "false").lower() == "true"
        # Offline model env vars
        self.model_receptionist = os.getenv("MODEL_RECEPTIONIST", "gemma4:e4b")
        self.model_orchestrator = os.getenv("MODEL_ORCHESTRATOR", "qwen3.5:27b-q4_K_M")
        self.model_code = os.getenv("MODEL_SPECIALIST_CODE", "gemma4:26b")
        # Online model env vars
        self.model_online_complex = os.getenv("MODEL_ONLINE_COMPLEX", "gemini-2.5-pro")
        self.model_online_medium = os.getenv("MODEL_ONLINE_MEDIUM", "gemini-2.5-flash")
        self.model_online_light = os.getenv("MODEL_ONLINE_LIGHT", "gemini-2.5-flash-lite")
        self.vertex_pro_threshold = int(os.getenv("COMPLEXITY_VERTEX_PRO", "8"))
        self.vertex_flash_threshold = int(os.getenv("COMPLEXITY_VERTEX_FLASH", "5"))

    def classify(self, message: str, context: str = "") -> dict:
        """
        Classify message complexity and recommend agent/tier.

        Args:
            message: The user's raw message string.
            context: Optional additional context (prior conversation, etc.)

        Returns:
            dict with keys: score (int 1-10), tier (str), recommended_agent (str),
            reasoning (str).
        """
        if not message or not message.strip():
            return {
                "score": 1,
                "tier": "light",
                "recommended_agent": "receptionist",
                "reasoning": "Empty or whitespace-only message defaults to light.",
            }

        msg_lower = message.lower().strip()
        word_count = len(msg_lower.split())
        candidate_scores: list[int] = []

        # ---- Rule 1: Very short / greeting → score 1-2 ----
        if word_count < 5 or any(g in msg_lower for g in _LIGHT_GREETINGS):
            candidate_scores.append(2)

        # ---- Rule 2: Light-medium factual patterns → score 3-4 ----
        if any(re.search(p, msg_lower) for p in _LIGHT_MEDIUM_PATTERNS):
            candidate_scores.append(4)

        # ---- Rule 3: Medium planning/research/comms → score 5-6 ----
        if any(kw in msg_lower for kw in _MEDIUM_KEYWORDS):
            candidate_scores.append(5)

        # ---- Rule 4: Code-related keywords → score 7-8 ----
        if any(kw in msg_lower for kw in _CODE_KEYWORDS):
            candidate_scores.append(8)

        # ---- Rule 5: Very long messages → score 9 ----
        if word_count > 200:
            candidate_scores.append(9)

        # ---- Rule 6: Multi-domain / "research AND implement" → score 9-10 ----
        if any(re.search(p, msg_lower) for p in _VERY_COMPLEX_MULTI):
            candidate_scores.append(10)

        # ---- Rule 7: Explicit multi-file / codebase analysis → score 9 ----
        if re.search(r"\bmultiple files?\b|\bcodebase\b|\barchitecture\b|\bdesign.*system\b", msg_lower):
            candidate_scores.append(9)

        # Default: medium if nothing matched
        if not candidate_scores:
            if word_count < 20:
                candidate_scores.append(3)
            else:
                candidate_scores.append(5)

        score = max(candidate_scores)
        score = max(1, min(10, score))  # clamp to [1, 10]

        tier = _score_to_tier(score)
        agent = _score_to_agent(score)

        reasoning = self._build_reasoning(msg_lower, score, word_count)

        return {
            "score": score,
            "tier": tier,
            "recommended_agent": agent,
            "reasoning": reasoning,
        }

    def _build_reasoning(self, msg_lower: str, score: int, word_count: int) -> str:
        """
        Build a one-sentence reasoning string for the classification.

        Args:
            msg_lower: Lowercased message.
            score: Computed complexity score.
            word_count: Number of words in the message.

        Returns:
            Human-readable reasoning string.
        """
        if score <= 2:
            return f"Short greeting or simple query ({word_count} words) — minimal processing required."
        if score <= 4:
            return f"Factual or status query ({word_count} words) — receptionist handles directly."
        if score <= 6:
            return f"Multi-step planning or research request — orchestrator coordinates the response."
        if score <= 8:
            return f"Code-related or technical task detected — code specialist engaged."
        return f"Complex multi-domain or codebase-level task ({word_count} words) — orchestrator with specialist delegation."

    def get_offline_model(self, agent_name: str, score: int) -> str:
        """
        Return the correct Ollama model tag for an agent given complexity score.

        If PROTOTYPE_MODE is true, always returns gemma4:e4b regardless of agent.

        Args:
            agent_name: Name of the target agent.
            score: Complexity score (1-10).

        Returns:
            Ollama model tag string.
        """
        if self.prototype_mode:
            return self.model_receptionist  # gemma4:e4b

        agent_model_map = {
            "receptionist": self.model_receptionist,
            "orchestrator": self.model_orchestrator,
            "code_specialist": self.model_code,
            "screen_vision_passive": self.model_receptionist,
            "screen_vision_deep": self.model_code,
            "browser_shopping": self.model_orchestrator,
            "research": self.model_orchestrator,
            "auditor": self.model_receptionist,
            "memory_distiller": self.model_receptionist,
            "file_manager": self.model_orchestrator,
            "voice_triage": self.model_receptionist,
            "system_control": self.model_orchestrator,
            "communication": self.model_orchestrator,
        }
        return agent_model_map.get(agent_name, self.model_receptionist)

    def get_online_model(self, score: int) -> str:
        """
        Return the correct Vertex AI model string based on complexity score.

        Args:
            score: Complexity score (1-10).

        Returns:
            Vertex AI / Gemini model name string.
        """
        if score >= self.vertex_pro_threshold:
            return self.model_online_complex
        if score >= self.vertex_flash_threshold:
            return self.model_online_medium
        return self.model_online_light
