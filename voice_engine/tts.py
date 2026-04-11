"""
J.A.R.V.I.S. — voice_engine/tts.py
Text-to-Speech engine stub. Full implementation in Phase 3.

Supports F5-TTS (primary, voice clone), Chatterbox-TTS (multilingual),
and Kokoro (fast/urgent). In Phase 1, text is printed to console.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bridging phrase bank
# ---------------------------------------------------------------------------

_BRIDGING_PHRASES: dict[str, str] = {
    "code": (
        "A complex development task, Sir. "
        "Give me just a moment to pull up my developer environment."
    ),
    "file": "Accessing your file system now, Sir. One moment.",
    "browser": "Opening a browser session for you, Sir. I will have that ready shortly.",
    "research": "Pulling up relevant sources, Sir. Conducting a search now.",
    "screen": "Taking control of the screen, Sir. Please stand by.",
    "analysis": (
        "This will require some thought, Sir. "
        "I am analyzing the full context now."
    ),
    "model_swap": (
        "Switching my specialist module for this task, Sir. Just a moment."
    ),
}


class TTSEngine:
    """
    Text-to-Speech engine for J.A.R.V.I.S.

    Phase 1 stub: logs and prints text to console.
    Phase 3 will activate F5-TTS, Chatterbox-TTS, and Kokoro.
    """

    def __init__(self) -> None:
        """
        Initialise TTS engine from environment variables.

        Attempts to import optional TTS libraries and warns gracefully
        if they are not installed.
        """
        self.primary_engine = os.getenv("TTS_ENGINE_PRIMARY", "f5tts")
        self.multilingual_engine = os.getenv("TTS_ENGINE_MULTILINGUAL", "chatterbox")
        self.fast_engine = os.getenv("TTS_ENGINE_FAST", "kokoro")
        self.voice_ref_file = os.getenv("TTS_VOICE_REF_FILE", "")
        self.voice_ref_text = os.getenv(
            "TTS_VOICE_REF_TEXT",
            "All systems are functioning within normal parameters, sir.",
        )
        self._f5tts_available = False
        self._chatterbox_available = False
        self._kokoro_available = False

        self._try_import_tts_libs()

    def _try_import_tts_libs(self) -> None:
        """
        Attempt to import optional TTS libraries.

        Logs a warning for each unavailable library so the server
        continues without crashing.
        """
        try:
            import f5_tts  # noqa: F401
            self._f5tts_available = True
            logger.info("F5-TTS available.")
        except ImportError:
            logger.warning(
                "F5-TTS not installed — TTS will print to console. "
                "Install with: pip install f5-tts"
            )

        try:
            import chatterbox  # noqa: F401
            self._chatterbox_available = True
            logger.info("Chatterbox-TTS available.")
        except ImportError:
            logger.warning(
                "Chatterbox-TTS not installed. "
                "Install with: pip install chatterbox-tts"
            )

        try:
            import kokoro  # noqa: F401
            self._kokoro_available = True
            logger.info("Kokoro-TTS available.")
        except ImportError:
            logger.warning(
                "Kokoro-TTS not installed. "
                "Install with: pip install kokoro-onnx"
            )

    async def speak(
        self,
        text: str,
        language: str = "en",
        urgent: bool = False,
    ) -> bool:
        """
        Speak text using the appropriate TTS engine.

        Selects the engine based on urgency and language:
        - urgent=True → Kokoro (fastest)
        - language != "en" → Chatterbox-TTS (multilingual)
        - default → F5-TTS with voice reference

        Splits text into sentences for streaming output (does not wait
        for the full text to be synthesised before starting playback).

        Args:
            text: The text to speak aloud.
            language: ISO 639-1 language code (default: "en").
            urgent: If True, use the fastest TTS engine for immediate output.

        Returns:
            True if spoken (or printed) successfully.
        """
        if not text or not text.strip():
            return False

        # Sentence-level split for streaming
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())

        for sentence in sentences:
            if not sentence.strip():
                continue
            await self._output_sentence(sentence.strip(), language=language, urgent=urgent)

        return True

    async def _output_sentence(
        self,
        sentence: str,
        language: str = "en",
        urgent: bool = False,
    ) -> None:
        """
        Output a single sentence via the chosen TTS backend.

        In Phase 1: prints to console prefixed with [JARVIS].
        In Phase 3: will call the actual TTS library.

        Args:
            sentence: Single sentence string to speak.
            language: Language code.
            urgent: If True, prefer the fastest engine.
        """
        # Determine which engine to use (Phase 3 will wire these up)
        if urgent and self._kokoro_available:
            engine_label = "kokoro"
        elif language != "en" and self._chatterbox_available:
            engine_label = "chatterbox"
        elif self._f5tts_available:
            engine_label = "f5-tts"
        else:
            engine_label = "console"

        if engine_label == "console":
            print(f"[JARVIS]: {sentence}")
        else:
            # Phase 3 implementation placeholder
            # The actual TTS call goes here when Phase 3 is built
            logger.debug("TTS (%s) — would speak: %s", engine_label, sentence[:60])
            print(f"[JARVIS TTS/{engine_label}]: {sentence}")

    async def speak_bridging_phrase(self, task_type: str) -> None:
        """
        Immediately speak a bridging phrase while a specialist model loads.

        Called before switching to a heavier model so the user is not left
        in silence during the model load time.

        Args:
            task_type: One of: code, file, browser, research, screen, analysis, model_swap.
        """
        phrase = _BRIDGING_PHRASES.get(
            task_type,
            "One moment, Sir. Engaging the appropriate specialist now.",
        )
        await self.speak(phrase)
