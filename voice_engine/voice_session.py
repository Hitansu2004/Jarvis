"""
J.A.R.V.I.S. — voice_engine/voice_session.py
Voice session coordinator with full conversation loop.

Features:
- Wake word → listen → answer → conversation mode (no wake word needed for follow-ups)
- VAD-based recording (auto-stops when you stop talking)
- Say "goodbye/sleep/goodnight" to go dormant
- Returns to wake word listening after 60s idle
- Works 24/7 — always ready when you say "Hey Jarvis" or "Jarvis"

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

# Words that put Jarvis back to sleep (wake word mode)
FAREWELL_WORDS = {
    # English
    "goodbye", "bye", "bye bye", "good night", "goodnight",
    "sleep", "stop listening", "go to sleep", "that's all",
    "that is all", "you can go", "standby", "stand by", "dismissed",
    
    # Hindi (Devanagari)
    "अलविदा", "बाद में मिलते हैं", "सो जाओ", "चलो बाद में बात करते हैं",
    "बंद करो", "अभी के लिए बस", "शुभ रात्रि", "बाई", "बद्बाई",
    
    # Hinglish
    "alvida", "so jao", "chalo baad mein", "bas itna hi", "shubh ratri"
}


class VoiceSessionManager:
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CONVERSATION = "conversation"
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
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Conversation mode: how long to stay active after an answer (seconds)
        self._conversation_timeout = float(os.environ.get("VOICE_CONVERSATION_TIMEOUT", "60"))

        logger.info("VoiceSessionManager initialized. State: IDLE")

    def start(self) -> None:
        """Start the voice session manager — begins wake word listening."""
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
        self._wwd.start()
        logger.info("VoiceSessionManager started — listening for wake word.")

    def stop(self) -> None:
        """Stop all voice components cleanly."""
        self._wwd.stop()

    def _on_wake_word_detected(self) -> None:
        """Called by WakeWordDetector when wake word is heard (from background thread)."""
        if self._state not in (self.IDLE, self.CONVERSATION):
            return  # Don't interrupt if already processing

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._handle_voice_session(), self._loop)
        else:
            logger.warning("Wake word detected but event loop not available.")

    async def _handle_voice_session(self) -> None:
        """
        Full session pipeline:
        1. Pause wake word mic (yield to VAD)
        2. Listen with VAD (auto-stops on silence)
        3. Transcribe → LLM → Speak
        4. Conversation mode (60s direct follow-up)
        5. Resume wake word mic
        """
        async with self._state_lock:
            if self._state not in (self.IDLE, self.CONVERSATION):
                return
            self._state = self.RECORDING
            self._current_session_id = str(uuid.uuid4())

        # Pause wake word mic BEFORE opening VAD InputStream
        # Sleep 400ms to let the detection loop actually close its InputStream
        self._wwd.pause()
        await asyncio.sleep(0.4)
        try:
            # ── Step 1: Record with VAD ──
            self._state = self.RECORDING
            text = await self._stt.record_with_vad(
                max_duration=30.0,
                silence_timeout=1.5,
                prompt_text="Speak your question...",
            )

            if not text or not text.strip():
                print("\n💤 [JARVIS] — No speech detected. Listening for wake word.\n")
                self._state = self.IDLE
                return

            # ── Step 2: Check for farewell ──
            if self._is_farewell(text):
                print(f"\n💬 YOU: {text}")
                await self._tts.speak("Goodnight Sir. I'll be standing by whenever you need me.")
                print("💤 [JARVIS] — Going dormant. Say 'Hey Jarvis' to wake me.\n")
                self._state = self.IDLE
                return

            # ── Step 3: Process with AI ──
            self._state = self.PROCESSING
            if self._on_transcription_callback:
                await self._on_transcription_callback(text, self._current_session_id)

            # ── Step 4: Conversation mode ──
            await self._conversation_loop()

        except Exception as e:
            logger.error("Voice session pipeline failed: %s", e)
            self._state = self.IDLE
        finally:
            # Always resume wake word mic regardless of outcome
            self._wwd.resume()
            logger.debug("Wake word mic resumed.")


    async def _conversation_loop(self) -> None:
        """
        After answering, stay active for up to 60 seconds for follow-ups.
        Pause/resume mic around each VAD listen to prevent InputStream conflict.
        """
        self._state = self.CONVERSATION
        start_time = time.time()
        timeout = self._conversation_timeout

        print(f"\n💬 [CONVERSATION MODE] — Speak a follow-up or say 'goodbye' to sleep.\n")

        while time.time() - start_time < timeout:
            # Pause wake word, take mic for follow-up listen
            self._wwd.pause()
            try:
                text = await self._stt.record_with_vad(
                    max_duration=20.0,
                    silence_timeout=2.0,
                    prompt_text="Follow-up? (or say 'goodbye' to sleep)",
                )
            finally:
                self._wwd.resume()

            if not text or not text.strip():
                elapsed = time.time() - start_time
                if elapsed >= timeout - 5:
                    break
                continue

            if self._is_farewell(text):
                print(f"\n💬 YOU: {text}")
                await self._tts.speak("Understood. Goodnight Sir. I'll be standing by.")
                print("💤 [JARVIS] — Dormant. Say 'Hey Jarvis' to wake.\n")
                self._state = self.IDLE
                return

            if self._on_transcription_callback:
                self._state = self.PROCESSING
                await self._on_transcription_callback(text, str(uuid.uuid4()))
                self._state = self.CONVERSATION
                start_time = time.time()

        logger.info("Conversation mode timed out. Returning to wake word listening.")
        print("\n👂 [JARVIS] — Conversation timeout. Back to wake word mode. Say 'Hey Jarvis'.\n")
        self._state = self.IDLE


    def _is_farewell(self, text: str) -> bool:
        """Check if the user's message is a farewell/sleep command."""
        text_lower = text.lower().strip()
        # Direct match
        if text_lower in FAREWELL_WORDS:
            return True
        # Phrase contains a farewell word
        for word in FAREWELL_WORDS:
            if word in text_lower:
                return True
        return False

    async def speak_response(self, text: str, language: str = "auto") -> bool:
        """
        Speak a JARVIS response through TTS.
        language='hi' → uses hf_alpha (Hindi female voice)
        language='auto' or 'en' → uses af_heart (English female voice)
        """
        self._state = self.SPEAKING
        result = await self._tts.speak(text, language=language)
        self._state = self.CONVERSATION
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
