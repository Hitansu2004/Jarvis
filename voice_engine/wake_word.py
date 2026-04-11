"""
J.A.R.V.I.S. — voice_engine/wake_word.py
Wake word detection stub using openWakeWord. Full implementation in Phase 3.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Always-on wake word detector for J.A.R.V.I.S.

    Uses openWakeWord (~0.5% CPU) to listen for "Hey Jarvis".
    Phase 1 stub: logs startup message if openWakeWord is unavailable.
    Phase 3 will activate full audio stream detection.
    """

    def __init__(self, callback: Callable[[], None]) -> None:
        """
        Initialise the wake word detector.

        Args:
            callback: Zero-argument callable invoked when the wake word is detected.
                      The gateway passes a function that triggers voice processing.
        """
        self.wake_word: str = os.getenv("WAKE_WORD", "Hey Jarvis")
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._oww_available = False
        self._try_import_oww()

    def _try_import_oww(self) -> None:
        """
        Attempt to import openWakeWord.

        Logs a warning if not installed so the server continues without crashing.
        """
        try:
            import openwakeword  # noqa: F401
            self._oww_available = True
            logger.info("openWakeWord available — wake word: '%s'.", self.wake_word)
        except ImportError:
            logger.warning(
                "openWakeWord not installed — wake word detection disabled. "
                "Install with: pip install openwakeword"
            )

    def start(self) -> None:
        """
        Start the background wake word detection thread.

        CPU usage: ~0.5% with openWakeWord.
        Phase 1: prints a stub message. Phase 3 will activate audio stream.
        """
        if self._running:
            logger.warning("Wake word detector already running.")
            return

        self._running = True

        if not self._oww_available:
            print("[JARVIS]: Wake word detector started (stub) — openWakeWord not installed.")
            logger.info("Wake word detector stub started — '%s' not active.", self.wake_word)
            return

        self._thread = threading.Thread(
            target=self._detection_loop,
            daemon=True,
            name="jarvis-wake-word",
        )
        self._thread.start()
        logger.info("Wake word detector thread started — listening for '%s'.", self.wake_word)

    def stop(self) -> None:
        """
        Stop the background wake word detection thread.
        """
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Wake word detector stopped.")

    def _detection_loop(self) -> None:
        """
        Background detection loop. Phase 3 will wire this to a real audio stream.

        Currently a no-op loop waiting for Phase 3 implementation.
        """
        # Phase 3 implementation:
        # 1. Open pyaudio stream at 16 kHz mono
        # 2. Feed chunks to openwakeword model
        # 3. When activation score > threshold: call self.callback()
        logger.info("Wake word detection loop running (Phase 3 will activate audio stream).")
        while self._running:
            import time
            time.sleep(1)  # idle — Phase 3 will replace with audio processing
