"""
J.A.R.V.I.S. — voice_engine/stt.py
Speech-to-Text using OpenAI Whisper-small on Apple Silicon MPS.
~150ms transcription latency per utterance on M4 Pro.

Author: Hitansu Parichha | Nisum Technologies
Phase 3 — Blueprint v5.0
"""

import asyncio
import logging
import os
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

class STTEngine:
    def __init__(self):
        raw_model = os.environ.get("STT_MODEL", "whisper-small")
        if raw_model.startswith("whisper-"):
            self.model_name = raw_model.replace("whisper-", "", 1)
        else:
            self.model_name = raw_model
            
        self.device = os.environ.get("STT_DEVICE", "mps")
        self._sample_rate = 16000
        
        self._whisper_available = False
        self._is_loading = False
        self._model = None
        
        logger.info(
            "STTEngine initialized — model=%s will load on first use, device=%s",
            self.model_name, self.device
        )

    def _ensure_loaded(self) -> bool:
        """
        Lazy-load Whisper model on first use.
        Prevents slow startup — model loads only when first voice command arrives.
        """
        if self._whisper_available:
            return True
        if self._is_loading:
            return False  # Prevent double-load race
            
        self._is_loading = True
        try:
            import whisper
            logger.info("Loading Whisper-%s on device %s...", self.model_name, self.device)
            self._model = whisper.load_model(self.model_name, device=self.device)
            self._whisper_available = True
            logger.info("Whisper-%s loaded successfully on %s.", self.model_name, self.device)
            return True
        except ImportError:
            logger.warning("openai-whisper not installed. STT unavailable.")
            return False
        except RuntimeError as e:
            # MPS not available — fall back to CPU
            error_str = str(e).lower()
            if "mps" in error_str and self.device == "mps":
                logger.warning("MPS unavailable for Whisper, falling back to CPU.")
                self.device = "cpu"
                try:
                    import whisper
                    self._model = whisper.load_model(self.model_name, device="cpu")
                    self._whisper_available = True
                    return True
                except Exception as e2:
                    logger.error("Whisper CPU fallback also failed: %s", e2)
                    return False
            logger.error("Whisper load failed: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected STT load error: %s", e)
            return False
        finally:
            self._is_loading = False

    async def transcribe(self, audio_array: np.ndarray, language: Optional[str] = None) -> str:
        """
        Transcribe a numpy audio array to text.
        """
        if not self._ensure_loaded():
            return ""
            
        try:
            options = {}
            if language:
                options["language"] = language
                
            loop = asyncio.get_event_loop()
            
            def run_transcribe():
                return self._model.transcribe(audio_array, fp16=False, **options)
                
            result = await loop.run_in_executor(None, run_transcribe)
            text = result.get("text", "").strip()
            logger.debug("STT transcribed: '%s'", text[:100])
            return text
        except Exception as e:
            logger.error("Transcription failed: %s", e)
            return ""

    async def transcribe_file(self, file_path: str, language: Optional[str] = None) -> str:
        """
        Transcribe an audio file to text.
        """
        if not self._ensure_loaded():
            return ""
            
        try:
            loop = asyncio.get_event_loop()
            options = {"fp16": False}
            if language:
                options["language"] = language
                
            def run_file_transcribe():
                return self._model.transcribe(file_path, **options)
                
            result = await loop.run_in_executor(None, run_file_transcribe)
            return result.get("text", "").strip()
        except Exception as e:
            logger.error("File transcription failed for '%s': %s", file_path, e)
            return ""

    async def record_and_transcribe(self, duration_seconds: float = 5.0, language: Optional[str] = None) -> str:
        """
        Record from microphone and transcribe immediately.
        """
        try:
            import sounddevice as sd
            import numpy as np
            
            logger.info("Recording for %.1f seconds...", duration_seconds)
            loop = asyncio.get_event_loop()
            
            def start_recording():
                return sd.rec(
                    int(duration_seconds * self._sample_rate),
                    samplerate=self._sample_rate,
                    channels=1,
                    dtype="float32"
                )
                
            audio_data = await loop.run_in_executor(None, start_recording)
            await loop.run_in_executor(None, sd.wait)
            
            audio_array = audio_data.flatten()
            logger.debug("Recorded %d samples, transcribing...", len(audio_array))
            return await self.transcribe(audio_array, language=language)
            
        except ImportError:
            logger.warning("sounddevice not installed — cannot record from microphone.")
            return ""
        except Exception as e:
            logger.error("Recording failed: %s", e)
            return ""

    def get_status(self) -> dict:
        """Return STT engine status."""
        return {
            "whisper_available": self._whisper_available,
            "model_name": self.model_name,
            "device": self.device,
            "model_loaded": self._model is not None,
            "sample_rate": self._sample_rate,
        }

_instance: Optional[STTEngine] = None

def get_stt_engine() -> STTEngine:
    global _instance
    if _instance is None:
        _instance = STTEngine()
    return _instance
