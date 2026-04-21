"""
J.A.R.V.I.S. — screen_engine/suggestion_engine.py
Generates proactive suggestions based on screen context.
Implements the 5-second pause rule and 2-minute cooldown rule.

Author: Hitansu Parichha | Nisum Technologies
Phase 5 — Blueprint v6.0
"""

import time
import os
import logging
from typing import Optional
from screen_engine.context_classifier import ScreenContext, CONTEXT_CODE_EDITING, CONTEXT_SHOPPING

logger = logging.getLogger(__name__)

class SuggestionEngine:
    def __init__(self):
        # Read SUGGESTION_COOLDOWN_SECONDS from env (default 120)
        self._cooldown_seconds: int = int(os.getenv("SUGGESTION_COOLDOWN_SECONDS", "120"))
        # Read CODE_SUGGESTION_PAUSE from env (default 5.0)
        self._code_pause_required: float = float(os.getenv("CODE_SUGGESTION_PAUSE", "5.0"))
        
        self._last_suggestion_time: float = 0.0
        self._last_code_change_time: float = 0.0
        self._last_context_hash: str = ""
        self._observation_count: int = 0
        self._suppressed_until: float = 0.0

    def should_suggest(self, context: ScreenContext) -> bool:
        """
        Determine if it is appropriate to generate a suggestion now.

        Rules:
          1. If globally suppressed (suppress_for was called): False
          2. If cooldown period has not elapsed: False
          3. For code context: only if user has paused typing for 5+ seconds
             (approximated by checking if same file/line for 2+ observations)
          4. If context has not changed since last observation: reduce frequency
        """
        now = time.time()

        # Rule 1: Global suppression
        if self._suppressed_until > now:
            return False

        # Rule 2: Cooldown
        if now - self._last_suggestion_time < self._cooldown_seconds:
            return False

        # Rule 3: Code context — require same context for multiple observations
        # (This approximates the 5-second pause rule without keyboard monitoring)
        if context.is_coding:
            context_hash = f"{context.file_path}:{context.current_line}"
            if context_hash != self._last_context_hash:
                self._last_context_hash = context_hash
                self._observation_count = 0
                return False  # Context changed — wait for stability
            self._observation_count += 1
            if self._observation_count < 3:  # ~6 seconds at 2s interval
                return False

        return True

    def generate_suggestion(self, context: ScreenContext) -> str | None:
        """
        Generate a JARVIS-style proactive suggestion based on the current screen context.

        This method is called ONLY when should_suggest() returned True.
        Combines ScreenVision's suggestion with context-specific JARVIS language.

        Args:
            context: The current ScreenContext.

        Returns:
            Formatted suggestion string in JARVIS voice, or None if nothing useful.
        """
        # First try using the suggestion from vision output
        if context.suggestions:
            raw_sugg = context.suggestions[0]
            if raw_sugg and raw_sugg.lower() not in ("none", "n/a", "-"):
                return self._format_suggestion(raw_sugg, context)

        # Context-specific fallback suggestions
        if context.context_type == CONTEXT_CODE_EDITING and context.file_path:
            lang = context.language or "code"
            file_short = context.file_path.split("/")[-1] if "/" in context.file_path else context.file_path
            return (
                f"Sorry to interrupt, Sir. I can see you are working on {file_short}. "
                f"Shall I run a quick analysis for potential issues in the visible code?"
            )

        if context.context_type == CONTEXT_SHOPPING and context.site_name:
            return (
                f"Sorry to interrupt, Sir. I notice you are browsing on {context.site_name}. "
                f"Shall I search for alternatives or better pricing in the background?"
            )

        return None

    def _format_suggestion(self, raw: str, context: ScreenContext) -> str:
        """
        Format a raw suggestion into JARVIS proactive suggestion format.
        Format: "Sorry to interrupt, Sir. [Observation]. [Proposal]. Shall I?"
        """
        raw = raw.strip().rstrip(".")
        app_context = ""
        if context.is_coding and context.file_path:
            file_short = context.file_path.split("/")[-1] if "/" in context.file_path else context.file_path
            app_context = f" in {file_short}"

        return f"Sorry to interrupt, Sir. I noticed{app_context}: {raw}. Shall I address it?"

    def record_suggestion_delivered(self) -> None:
        """Call this after a suggestion has been delivered to reset the cooldown."""
        self._last_suggestion_time = time.time()
        self._observation_count = 0

    def suppress_for(self, seconds: int) -> None:
        """Suppress all suggestions for N seconds."""
        self._suppressed_until = time.time() + seconds
        logger.info("SuggestionEngine suppressed for %d seconds.", seconds)

    def is_suppressed(self) -> bool:
        """Check if suggestions are currently suppressed."""
        return time.time() < self._suppressed_until

    def get_status(self) -> dict:
        """Return suggestion engine status dict."""
        now = time.time()
        cooldown_remaining = max(0, self._cooldown_seconds - (now - self._last_suggestion_time))
        return {
            "suppressed": self.is_suppressed(),
            "suppressed_until": self._suppressed_until if self._suppressed_until > now else None,
            "cooldown_seconds": self._cooldown_seconds,
            "cooldown_remaining_seconds": round(cooldown_remaining),
            "observations_since_last_suggestion": self._observation_count,
        }

_engine_instance: Optional[SuggestionEngine] = None

def get_suggestion_engine() -> SuggestionEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SuggestionEngine()
    return _engine_instance
