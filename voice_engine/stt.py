"""
J.A.R.V.I.S. — voice_engine/stt.py
Speech-to-Text using OpenAI Whisper-small.
Runs on CPU (Apple Silicon MPS is not supported by Whisper-small).

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

        # Whisper-small does not support Apple Silicon MPS — CPU is correct and fast
        self.device = "cpu"
        self._sample_rate = 16000

        self._whisper_available = False
        self._is_loading = False
        self._model = None

        logger.info(
            "STTEngine initialized — model=whisper-%s | device=cpu (MPS not supported by Whisper)",
            self.model_name
        )

    def _ensure_loaded(self) -> bool:
        """
        Lazy-load Whisper model on first use.
        Always uses CPU — Whisper-small doesn't support MPS.
        """
        if self._whisper_available:
            return True
        if self._is_loading:
            return False

        self._is_loading = True
        try:
            import whisper
            logger.info("Loading Whisper-%s on CPU...", self.model_name)
            self._model = whisper.load_model(self.model_name, device="cpu")
            self._whisper_available = True
            logger.info("Whisper-%s ready.", self.model_name)
            return True
        except ImportError:
            logger.warning("openai-whisper not installed. STT unavailable.")
            return False
        except Exception as e:
            logger.error("Whisper load failed: %s", e)
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

    async def record_with_vad(
        self,
        max_duration: float = 30.0,
        silence_timeout: float = 1.5,
        prompt_text: str = "Speak your question..."
    ) -> str:
        """
        Record using Voice Activity Detection.
        Stops automatically when you stop speaking (after silence_timeout seconds of silence).
        Max duration is 30s to handle long complex questions.
        Shows smooth animated wave bars while listening.
        """
        try:
            import sounddevice as sd
            import numpy as np
            import sys

            CHUNK = 3200  # 200ms at 16kHz
            SILENCE_THRESH = 0.015  # RMS energy threshold for speech
            max_silence_chunks = int(silence_timeout * self._sample_rate / CHUNK)
            max_chunks = int(max_duration * self._sample_rate / CHUNK)

            frames = []
            silence_count = 0
            speech_started = False
            smooth_rms = 0.0

            print(f"\n🔴 [MIC ACTIVE] — {prompt_text}", flush=True)

            with sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=CHUNK
            ) as stream:
                for _ in range(max_chunks):
                    chunk, _ = stream.read(CHUNK)
                    frames.append(chunk)

                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    # Exponential smoothing for fluid bar animation
                    smooth_rms = 0.6 * smooth_rms + 0.4 * rms

                    bars = int(min(smooth_rms * 350, 30))
                    visual = "█" * bars + " " * (30 - bars)
                    sys.stdout.write(f"\r🎤 [{visual}]")
                    sys.stdout.flush()

                    if smooth_rms > SILENCE_THRESH:
                        speech_started = True
                        silence_count = 0
                    elif speech_started:
                        silence_count += 1
                        if silence_count >= max_silence_chunks:
                            break  # Auto-stop after silence detected

            print("\n✅ [MIC CLOSED] — Thinking...\n", flush=True)

            if not frames:
                return ""

            audio_array = np.concatenate(frames).flatten()
            logger.debug("VAD recorded %d samples (%.1fs)", len(audio_array),
                         len(audio_array) / self._sample_rate)
            return await self.transcribe(audio_array, language=None)

        except ImportError:
            logger.warning("sounddevice not installed — cannot record from microphone.")
            return ""
        except Exception as e:
            logger.error("VAD recording failed: %s", e)
            return ""

    async def record_and_transcribe(self, duration_seconds: float = 10.0, language: Optional[str] = None) -> str:
        """Legacy fixed-duration recording — now delegates to VAD."""
        return await self.record_with_vad(
            max_duration=duration_seconds,
            silence_timeout=1.5,
        )


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
