"""
J.A.R.V.I.S. — voice_engine/stt.py
Speech-to-Text engine stub using Whisper-small. Full implementation in Phase 3.

GAP 8 FIX: Whisper loads LAZILY on first transcribe() call, not at startup.
Per the RAM budget: "Whisper-small (STT) — 0.3 GB — When listening —
Loaded on wake word trigger" (Blueprint Appendix C).

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class STTEngine:
    """
    Speech-to-Text engine for J.A.R.V.I.S.

    Uses OpenAI Whisper-small for transcription.
    Phase 1 stub: returns placeholder if Whisper is unavailable.
    Phase 3 will activate full streaming transcription.

    GAP 8 FIX: Whisper is loaded LAZILY on first transcribe() call to avoid
    adding ~2-4 seconds to cold startup. The wake word detector triggers loading.
    """

    def __init__(self) -> None:
        """
        Initialise STT engine from environment variables.

        Does NOT load Whisper at startup — loading is deferred to first use.
        """
        self.model_name: str = os.getenv("STT_MODEL", "whisper-small").replace("whisper-", "")
        self.device: str = os.getenv("STT_DEVICE", "mps")
        self._model = None
        self._whisper_available: Optional[bool] = None  # None = not yet checked
        self._whisper_checked: bool = False              # prevent repeated failed imports
        logger.info(
            "STTEngine initialised (lazy load) — model=%s, device=%s",
            self.model_name,
            self.device,
        )

    def _ensure_loaded(self) -> None:
        """
        Load Whisper model on first use if not already loaded.

        Called by transcribe() and transcribe_file() before processing.
        Skips if already loaded or if a previous attempt already failed.
        """
        if self._whisper_checked:
            return  # Already attempted (success or failure) — don't retry
        self._try_load_whisper()
        self._whisper_checked = True

    def _try_load_whisper(self) -> None:
        """
        Attempt to import and load the Whisper model.

        Logs a warning and sets a flag if Whisper is not installed.
        Attempts CPU fallback if MPS/CUDA device fails.
        """
        try:
            import whisper
            self._model = whisper.load_model(self.model_name, device=self.device)
            self._whisper_available = True
            logger.info(
                "Whisper STT loaded — model=%s, device=%s", self.model_name, self.device
            )
        except ImportError:
            self._whisper_available = False
            logger.warning(
                "openai-whisper not installed — STT unavailable. "
                "Install with: pip install openai-whisper"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load Whisper model '%s' on device '%s': %s. "
                "Falling back to CPU.",
                self.model_name,
                self.device,
                exc,
            )
            # Attempt CPU fallback
            try:
                import whisper
                self._model = whisper.load_model(self.model_name, device="cpu")
                self._whisper_available = True
                logger.info("Whisper STT loaded on CPU as fallback.")
            except Exception as fallback_exc:  # noqa: BLE001
                self._whisper_available = False
                logger.error("Whisper CPU fallback also failed: %s", fallback_exc)

    async def transcribe(self, audio_array: np.ndarray) -> str:
        """
        Transcribe a float32 audio array to text.

        Loads Whisper on first call (lazy loading — GAP 8 fix).

        Args:
            audio_array: NumPy float32 array of audio samples at 16 kHz.

        Returns:
            Transcribed text string, or placeholder if Whisper is unavailable.
        """
        self._ensure_loaded()  # GAP 8 FIX: lazy load on first call

        if not self._whisper_available or self._model is None:
            return "STT not yet initialized — Phase 3 will activate Whisper transcription."

        try:
            result = self._model.transcribe(audio_array, fp16=False)
            return result.get("text", "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("Whisper transcription error: %s", exc)
            return "Transcription error — please try again, Sir."

    async def transcribe_file(self, file_path: str) -> str:
        """
        Load an audio file and transcribe it to text.

        Loads Whisper on first call (lazy loading — GAP 8 fix).

        Args:
            file_path: Absolute or relative path to the audio file.

        Returns:
            Transcribed text string, or placeholder if Whisper is unavailable.
        """
        self._ensure_loaded()  # GAP 8 FIX: lazy load on first call

        if not self._whisper_available or self._model is None:
            return "STT not yet initialized — Phase 3 will activate Whisper transcription."

        try:
            import whisper
            audio = whisper.load_audio(file_path)
            audio = whisper.pad_or_trim(audio)
            result = self._model.transcribe(audio, fp16=False)
            return result.get("text", "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("Whisper file transcription error for '%s': %s", file_path, exc)
            return f"Could not transcribe file, Sir: {exc}"
