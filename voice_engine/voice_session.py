"""
J.A.R.V.I.S. — voice_engine/voice_session.py
Voice session coordinator. Manages the full voice pipeline:
  wake word → STT recording → intent classification → agent dispatch
  → LLM response → TTS streaming output → return to listening

Author: Hitansu Parichha | Nisum Technologies
Phase 3 — Blueprint v5.0
"""

import asyncio
import logging
import time
import uuid
from typing import Callable, Optional

from voice_engine.stt import get_stt_engine
from voice_engine.tts import get_tts_engine
from voice_engine.wake_word import get_wake_word_detector

logger = logging.getLogger(__name__)

class VoiceSessionManager:
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    COOLDOWN = "cooldown"

    def __init__(self):
        import os
        self._tts = get_tts_engine()
        self._stt = get_stt_engine()
        self._wwd = get_wake_word_detector(callback=self._on_wake_word_detected)
        
        self._state = self.IDLE
        self._current_session_id: Optional[str] = None
        self._state_lock = asyncio.Lock()
        
        self._suggestion_suppressed_until: float = 0.0
        self._suppressed_suggestions: list[str] = []
        self._on_transcription_callback: Optional[Callable] = None
        
        self._recording_duration = float(os.environ.get("VOICE_RECORDING_DURATION", "5.0"))
        
        logger.info("VoiceSessionManager initialized. State: IDLE")

    def start(self) -> None:
        """Start the voice session manager — begins wake word listening."""
        self._wwd.start()
        logger.info("VoiceSessionManager started — listening for wake word.")

    def stop(self) -> None:
        """Stop all voice components cleanly."""
        self._wwd.stop()

    def _on_wake_word_detected(self) -> None:
        """Called by WakeWordDetector when wake word is heard."""
        if self._state != self.IDLE:
            return  # don't interrupt if already processing
            
        loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self._handle_voice_command(), loop)

    async def _handle_voice_command(self) -> None:
        """Full pipeline from wake word to TTS response."""
        async with self._state_lock:
            self._state = self.RECORDING
            self._current_session_id = str(uuid.uuid4())

        try:
            self._state = self.RECORDING
            text = await self._stt.record_and_transcribe(self._recording_duration)

            if not text.strip():
                self._state = self.IDLE
                return

            self._state = self.TRANSCRIBING
            logger.info("Voice command transcribed: '%s'", text)

            # Notify gateway (if callback set)
            if self._on_transcription_callback:
                self._state = self.PROCESSING
                await self._on_transcription_callback(text, self._current_session_id)

            self._state = self.IDLE
        except Exception as e:
            logger.error("Voice command pipeline failed: %s", e)
            self._state = self.IDLE

    async def speak_response(self, text: str, language: str = "en") -> bool:
        """
        Speak a JARVIS response through TTS.
        Called by gateway after agent produces a response.
        """
        self._state = self.SPEAKING
        result = await self._tts.speak(text, language=language)
        self._state = self.IDLE
        return result

    async def speak_immediately(self, text: str, urgent: bool = False) -> bool:
        """Speak without changing session state — for system messages."""
        return await self._tts.speak(text, urgent=urgent)

    def suppress_suggestions(self, seconds: int) -> None:
        """Suppress proactive suggestions for N seconds."""
        self._suggestion_suppressed_until = time.time() + seconds
        logger.info("Suggestions suppressed for %d seconds.", seconds)

    def is_suggestion_suppressed(self) -> bool:
        """Check if suggestions are currently suppressed."""
        return time.time() < self._suggestion_suppressed_until

    def queue_suppressed_suggestion(self, suggestion: str) -> None:
        """Store a suggestion that was suppressed during cooldown."""
        self._suppressed_suggestions.append(suggestion)

    def get_suppressed_suggestions(self) -> list[str]:
        """Return and clear all suggestions generated during suppression."""
        suggestions = list(self._suppressed_suggestions)
        self._suppressed_suggestions.clear()
        return suggestions

    def get_status(self) -> dict:
        return {
            "state": self._state,
            "tts": self._tts.get_status(),
            "stt": self._stt.get_status(),
            "wake_word": self._wwd.get_status(),
            "suggestion_suppressed": self.is_suggestion_suppressed(),
            "suppressed_until": self._suggestion_suppressed_until if self.is_suggestion_suppressed() else None,
            "suppressed_suggestion_count": len(self._suppressed_suggestions),
        }

    def set_transcription_callback(self, callback: Callable) -> None:
        """Set callback for when a voice command is transcribed."""
        self._on_transcription_callback = callback

_instance: Optional[VoiceSessionManager] = None

def get_voice_session_manager() -> VoiceSessionManager:
    global _instance
    if _instance is None:
        _instance = VoiceSessionManager()
    return _instance
