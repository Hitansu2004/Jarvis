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
from screen_engine.context_classifier import get_context_classifier, ContextClassifier
from screen_engine.suggestion_engine import get_suggestion_engine, SuggestionEngine


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
        self._vision: Optional[ScreenVision] = None  # injected from gateway
        self._mode_manager = None  # injected from gateway
        self._agent_registry = None  # injected from gateway
        self._tts_speak_callback: Optional[Callable[[str], None]] = None  # injected
        self._context_classifier: ContextClassifier = get_context_classifier()
        self._suggestion_engine: SuggestionEngine = get_suggestion_engine()
        self._last_context: Optional[dict] = None  # cache last screen context

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

    def inject_dependencies(
        self,
        vision,
        mode_manager,
        agent_registry,
        tts_speak_callback: Callable[[str], None],
    ) -> None:
        """
        Inject gateway singletons after PassiveWatcher is created.
        Called from gateway lifespan startup after all singletons are ready.

        Args:
            vision: ScreenVision singleton.
            mode_manager: ModeManager singleton.
            agent_registry: AgentRegistry singleton.
            tts_speak_callback: Async function to speak a string via TTS.
        """
        self._vision = vision
        self._mode_manager = mode_manager
        self._agent_registry = agent_registry
        self._tts_speak_callback = tts_speak_callback
        logger.info("PassiveWatcher dependencies injected.")

    async def _process_one_frame(self) -> None:
        """
        Process a single observation cycle.
        Called from _watch_loop in an async context.
        """
        if not self._vision or not self._mode_manager:
            return  # Dependencies not injected yet

        try:
            # Capture and describe screen
            vision_output = await self._vision.capture_and_describe(
                deep=False,
                mode_manager=self._mode_manager,
                agent_registry=self._agent_registry,
            )

            # Classify context
            context = self._context_classifier.classify(vision_output)
            self._last_context = vision_output

            # Log observation to memory (Phase 4 integration)
            if self._conv_logger:
                observation_text = self._context_classifier.to_memory_observation(context)
                if observation_text:
                    self._conv_logger.log_screen_observation(
                        observation=observation_text,
                        source="passive_watcher",
                    )

            # Check if we should generate a suggestion
            if not self._suggestion_engine.is_suppressed():
                if self._suggestion_engine.should_suggest(context):
                    suggestion_text = self._suggestion_engine.generate_suggestion(context)
                    if suggestion_text:
                        now = time.monotonic()
                        if now < self._suppression_until:
                            # Suggestions suppressed — queue it
                            self.suppressed_suggestions.append(suggestion_text)
                            logger.debug("Suggestion queued (suppressed): %s", suggestion_text[:60])
                        else:
                            # Deliver suggestion via TTS
                            self._suggestion_engine.record_suggestion_delivered()
                            self.last_suggestion_time = time.time()
                            logger.info("Proactive suggestion: %s", suggestion_text[:80])
                            if self._tts_speak_callback:
                                try:
                                    await self._tts_speak_callback(suggestion_text)
                                except Exception as tts_exc:
                                    logger.warning("TTS suggestion delivery failed: %s", tts_exc)

        except Exception as exc:
            logger.error("PassiveWatcher frame processing error: %s", exc)

    def _watch_loop(self) -> None:
        """
        Main background loop — captures screenshot every 2 seconds,
        classifies context, generates suggestions, logs observations.

        Phase 5 full implementation.
        """
        import asyncio

        # Check if passive vision is enabled
        if not os.getenv("SCREEN_VISION_ENABLED", "true").lower() == "true":
            logger.info("SCREEN_VISION_ENABLED=false — PassiveWatcher idle.")
            while self.running:
                time.sleep(2)
            return

        logger.info("PassiveWatcher active — capturing every 2 seconds.")

        while self.running:
            time.sleep(2)  # 0.5 Hz capture rate

            # Check passive learning pause
            pause_minutes = int(os.getenv("PASSIVE_LEARNING_PAUSE_MINUTES", "0"))
            if pause_minutes > 0:
                logger.debug("Passive learning paused for %d more minutes.", pause_minutes)
                continue

            # Run async frame processing in the thread's event loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._process_one_frame())
                finally:
                    loop.close()
            except Exception as exc:
                logger.error("PassiveWatcher loop error: %s", exc)

    def get_last_context(self) -> Optional[dict]:
        """Return the most recent vision output dict, or None if no frames processed yet."""
        return self._last_context

    def get_status(self) -> dict:
        """Return full PassiveWatcher status."""
        return {
            "running": self.running,
            "screen_vision_enabled": os.getenv("SCREEN_VISION_ENABLED", "true").lower() == "true",
            "cooldown_seconds": self.cooldown_seconds,
            "vision_injected": self._vision is not None,
            "mode_manager_injected": self._mode_manager is not None,
            "last_context": self._last_context,
            "suggestion_engine": self._suggestion_engine.get_status() if self._suggestion_engine else {},
        }
