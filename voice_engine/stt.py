"""
J.A.R.V.I.S. — voice_engine/stt.py
Speech-to-Text engine stub using Whisper-small. Full implementation in Phase 3.

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
    """

    def __init__(self) -> None:
        """
        Initialise STT engine from environment variables.

        Attempts to load Whisper model; warns gracefully if unavailable.
        """
        self.model_name: str = os.getenv("STT_MODEL", "whisper-small").replace("whisper-", "")
        self.device: str = os.getenv("STT_DEVICE", "mps")
        self._model = None
        self._whisper_available = False
        self._try_load_whisper()

    def _try_load_whisper(self) -> None:
        """
        Attempt to import and load the Whisper model.

        Logs a warning and sets a flag if Whisper is not installed.
        """
        try:
            import whisper
            self._model = whisper.load_model(self.model_name, device=self.device)
            self._whisper_available = True
            logger.info(
                "Whisper STT loaded — model=%s, device=%s", self.model_name, self.device
            )
        except ImportError:
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
                logger.error("Whisper CPU fallback also failed: %s", fallback_exc)

    async def transcribe(self, audio_array: np.ndarray) -> str:
        """
        Transcribe a float32 audio array to text.

        Args:
            audio_array: NumPy float32 array of audio samples at 16 kHz.

        Returns:
            Transcribed text string, or placeholder if Whisper is unavailable.
        """
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

        Args:
            file_path: Absolute or relative path to the audio file.

        Returns:
            Transcribed text string, or placeholder if Whisper is unavailable.
        """
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
