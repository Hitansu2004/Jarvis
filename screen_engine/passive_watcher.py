"""
J.A.R.V.I.S. — screen_engine/passive_watcher.py
Background passive screen monitor stub. Full implementation in Phase 5.
Phase 4 adds memory logging hook so screen observations feed the nightly distiller.

Author: Hitansu Parichha | Nisum Technologies
Phase 4 — Blueprint v6.0
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Phase 4: import ConversationLogger for memory integration
try:
    from memory_vault.logger import ConversationLogger
    _CONV_LOGGER_AVAILABLE = True
except ImportError:
    _CONV_LOGGER_AVAILABLE = False


class PassiveWatcher:
    """
    Background passive screen monitor for J.A.R.V.I.S.

    Every 2 seconds: captures a screenshot and passes it to the
    screen_vision_passive agent. If a suggestion is generated AND the
    cooldown period has elapsed, the suggestion_callback is called.

    Phase 1 stub: the thread starts but takes no screenshots.
    Phase 5 will activate full vision-based monitoring.
    """

    def __init__(self, suggestion_callback: Callable[[str], None]) -> None:
        """
        Initialise the passive watcher.

        Args:
            suggestion_callback: Callable that receives a suggestion string
                                  when JARVIS has something to say.
        """
        self.running: bool = False
        self.suggestion_callback = suggestion_callback
        self.last_suggestion_time: float = 0.0
        self.cooldown_seconds: int = int(
            os.getenv("SUGGESTION_COOLDOWN_SECONDS", "120")
        )
        self.suppressed_suggestions: list[str] = []
        self._suppression_until: float = 0.0
        self._thread: Optional[threading.Thread] = None
        # Phase 4: memory logging hook
        self._conv_logger = ConversationLogger() if _CONV_LOGGER_AVAILABLE else None

    def start(self) -> None:
        """
        Start the background passive monitoring thread.

        Thread runs at ~0.5 Hz (every 2 seconds) to minimise CPU impact.
        Phase 1: thread starts but does not capture screenshots.
        """
        if self.running:
            logger.warning("PassiveWatcher already running.")
            return

        self.running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="jarvis-passive-watcher",
        )
        self._thread.start()
        logger.info(
            "PassiveWatcher started — cooldown=%ds (Phase 5 will activate screenshots).",
            self.cooldown_seconds,
        )

    def stop(self) -> None:
        """
        Stop the background passive monitoring thread.
        """
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("PassiveWatcher stopped.")

    def suppress_for(self, seconds: int) -> None:
        """
        Suppress all suggestions for the specified number of seconds.

        Any suggestions generated during suppression are queued and
        can be retrieved via get_suppressed_suggestions().

        Args:
            seconds: Duration in seconds to suppress suggestions.
        """
        self._suppression_until = time.monotonic() + seconds
        logger.info("PassiveWatcher suggestions suppressed for %d seconds.", seconds)

    def get_suppressed_suggestions(self) -> list[str]:
        """
        Return and clear the list of suppressed suggestions.

        Returns:
            List of suggestion strings that were queued during suppression.
        """
        result = list(self.suppressed_suggestions)
        self.suppressed_suggestions.clear()
        return result

    def _watch_loop(self) -> None:
        """
        Main background loop. Phase 5 will add screenshot capture and inference.
        Phase 4 adds memory logging hook for any observations generated.
        """
        logger.info("PassiveWatcher loop running (Phase 5 stub — no screenshots yet).")
        while self.running:
            time.sleep(2)

            # Phase 4: Check PASSIVE_LEARNING_PAUSE_MINUTES
            pause_minutes = int(os.getenv("PASSIVE_LEARNING_PAUSE_MINUTES", "0"))
            if pause_minutes > 0:
                # Simple implementation: skip this observation cycle
                continue

            # Phase 5 will:
            # 1. Capture screenshot via ScreenVision.capture_screenshot()
            # 2. Pass to screen_vision_passive agent via ModeManager
            # 3. Parse response to get observation_text
            # 4. If suggestion and cooldown elapsed: call self.suggestion_callback()
            # 5. If suppressed: append to self.suppressed_suggestions

            # Phase 4 memory hook (called once Phase 5 sets observation_text):
            # observation_text = ""  # Phase 5 fills this
            # if self._conv_logger and observation_text:
            #     self._conv_logger.log_screen_observation(
            #         observation=observation_text,
            #         source="passive_watcher",
            #     )
