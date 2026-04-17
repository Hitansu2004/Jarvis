"""
J.A.R.V.I.S. — voice_engine/tts.py
Text-to-Speech engine with F5-TTS (voice clone), Chatterbox (multilingual),
and Kokoro (ultra-fast fallback). Streaming sentence-by-sentence output.

Author: Hitansu Parichha | Nisum Technologies
Phase 3 — Blueprint v5.0
"""

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class TTSEngine:
    def __init__(self):
        self._f5tts_model = None
        self._kokoro_pipeline = None
        self._chatterbox_model = None
        self._f5tts_available = False
        self._chatterbox_available = False
        self._kokoro_available = False
        
        self.voice_ref_file = os.environ.get("TTS_VOICE_REF_FILE", "jarvis_ref.wav")
        self.voice_ref_text = os.environ.get("TTS_VOICE_REF_TEXT", "")
        self.primary_engine = os.environ.get("TTS_ENGINE_PRIMARY", "f5tts")
        self.multilingual_engine = os.environ.get("TTS_ENGINE_MULTILINGUAL", "chatterbox")
        self.fast_engine = os.environ.get("TTS_ENGINE_FAST", "kokoro")
        
        current_dir = Path(__file__).parent
        self._audio_output_dir = current_dir / "audio_output"
        self._audio_output_dir.mkdir(parents=True, exist_ok=True)
        
        self._sentence_pattern = re.compile(r'(?<=[.!?])\s+')
        
        self._try_load_kokoro()
        self._try_load_f5tts()
        self._try_load_chatterbox()
        
        logger.info(
            "TTS Initialization complete. F5-TTS: %s, Kokoro: %s, Chatterbox: %s",
            self._f5tts_available, self._kokoro_available, self._chatterbox_available
        )

    def _try_load_kokoro(self) -> None:
        try:
            from kokoro_onnx import Kokoro
            # The model files will be automatically downloaded by kokoro-onnx 
            # if they don't exist.
            self._kokoro_pipeline = Kokoro("kokoro-v0_19.onnx", "voices.bin")
            self._kokoro_available = True
            logger.info("Kokoro TTS loaded successfully.")
        except ImportError:
            logger.warning("kokoro-onnx not installed. Kokoro TTS unavailable.")
            self._kokoro_available = False
        except Exception as e:
            logger.warning("Failed to load Kokoro TTS: %s", e)
            self._kokoro_available = False

    def _try_load_f5tts(self) -> None:
        ref_path = Path(os.path.expanduser(self.voice_ref_file))
        if not ref_path.exists():
            logger.warning(
                "No Jarvis reference audio found at %s. F5-TTS will not be available. "
                "See Phase 3 setup guide for voice cloning.", ref_path
            )
            self._f5tts_available = False
            return
            
        try:
            from f5_tts.api import F5TTS
            self._f5tts_model = F5TTS()
            self._f5tts_available = True
            logger.info("F5-TTS loaded. Jarvis voice clone ready.")
        except ImportError:
            logger.warning("f5_tts not installed. F5-TTS unavailable.")
            self._f5tts_available = False
        except Exception as e:
            logger.warning("Failed to load F5-TTS: %s", e)
            self._f5tts_available = False

    def _try_load_chatterbox(self) -> None:
        try:
            from chatterbox.tts import ChatterboxTTS
            import torch
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            self._chatterbox_model = ChatterboxTTS.from_pretrained(device=device)
            self._chatterbox_available = True
            logger.info("Chatterbox TTS loaded on device: %s", device)
        except ImportError:
            logger.warning("chatterbox-tts not installed. Chatterbox unavailable.")
            self._chatterbox_available = False
        except Exception as e:
            logger.warning("Failed to load Chatterbox TTS: %s", e)
            self._chatterbox_available = False

    def _split_sentences(self, text: str) -> list[str]:
        # Split on newlines first, then split by sentence boundary
        lines = text.split('\n')
        sentences = []
        for line in lines:
            parts = self._sentence_pattern.split(line)
            for part in parts:
                cleaned = part.strip()
                if len(cleaned) >= 3:
                    sentences.append(cleaned)
        return sentences

    def _select_engine(self, language: str = "en", urgent: bool = False) -> str:
        if urgent:
            if self._kokoro_available:
                return "kokoro"
            return "console"
            
        if language != "en":
            if self._chatterbox_available:
                return "chatterbox"
            if self._kokoro_available:
                return "kokoro"
            return "console"
            
        # Default (English, not urgent)
        if self._f5tts_available:
            return "f5tts"
        if self._kokoro_available:
            return "kokoro"
        if self._chatterbox_available:
            return "chatterbox"
        return "console"

    async def speak(self, text: str, language: str = "en", urgent: bool = False) -> bool:
        """
        Speak text aloud using the best available TTS engine.
        Streams sentence-by-sentence — first sentence plays while rest generates.

        Args:
            text: Text to speak. May be multiple sentences.
            language: ISO 639-1 code. "en" = English, "hi" = Hindi, etc.
            urgent: If True, use fastest engine (Kokoro) regardless of language.

        Returns:
            True if spoken successfully, False if all engines failed.
        """
        if not text or not text.strip():
            return False
            
        sentences = self._split_sentences(text)
        if not sentences:
             return False
             
        engine = self._select_engine(language, urgent)
        success = False
        for sentence in sentences:
            result = await self._speak_sentence(sentence, engine, language)
            if result:
                success = True
        return success

    async def _speak_sentence(self, sentence: str, engine: str, language: str = "en") -> bool:
        """Speak a single sentence using the specified engine."""
        loop = asyncio.get_event_loop()
        
        if engine == "f5tts":
            try:
                output_file = self._audio_output_dir / f"jarvis_{uuid.uuid4().hex[:8]}.wav"
                
                def run_f5tts():
                    self._f5tts_model.infer(
                        ref_file=self.voice_ref_file,
                        ref_text=self.voice_ref_text,
                        gen_text=sentence,
                        output=str(output_file),
                    )
                    
                await loop.run_in_executor(None, run_f5tts)
                await self._play_audio(str(output_file))
                output_file.unlink(missing_ok=True)
                return True
            except Exception as e:
                logger.error("F5-TTS inference failed: %s", e)
                print(f"[JARVIS]: {sentence}")
                return True

        elif engine == "kokoro":
            try:
                import soundfile as sf
                
                # Format lang correctly for kokoro-onnx
                lang_code = language[:2].lower()
                lang_param = f"{lang_code}-us" if lang_code == "en" else lang_code
                
                def run_kokoro():
                    return self._kokoro_pipeline(
                        sentence,
                        voice="af_heart",
                        speed=1.0,
                        lang=lang_param,
                    )
                    
                samples, sample_rate = await loop.run_in_executor(None, run_kokoro)
                
                output_file = self._audio_output_dir / f"kokoro_{uuid.uuid4().hex[:8]}.wav"
                
                def save_sf():
                     sf.write(str(output_file), samples, sample_rate)
                     
                await loop.run_in_executor(None, save_sf)
                await self._play_audio(str(output_file))
                output_file.unlink(missing_ok=True)
                return True
            except Exception as e:
                logger.error("Kokoro TTS failed: %s", e)
                print(f"[JARVIS]: {sentence}")
                return True

        elif engine == "chatterbox":
            try:
                import torch
                import torchaudio
                
                def run_chatterbox():
                    return self._chatterbox_model.generate(sentence)
                    
                wav = await loop.run_in_executor(None, run_chatterbox)
                
                output_file = self._audio_output_dir / f"chatterbox_{uuid.uuid4().hex[:8]}.wav"
                
                def save_ta():
                    torchaudio.save(str(output_file), wav, self._chatterbox_model.sr)
                    
                await loop.run_in_executor(None, save_ta)
                await self._play_audio(str(output_file))
                output_file.unlink(missing_ok=True)
                return True
            except Exception as e:
                logger.error("Chatterbox TTS failed: %s", e)
                print(f"[JARVIS]: {sentence}")
                return True

        elif engine == "console":
            print(f"[JARVIS]: {sentence}")
            return True

        return False

    async def _play_audio(self, file_path: str) -> None:
        """
        Play an audio file through the system speakers.
        Uses sounddevice + soundfile for cross-platform playback.
        Falls back to subprocess (afplay on macOS, aplay on Linux) if sounddevice fails.
        """
        loop = asyncio.get_event_loop()
        
        try:
            import sounddevice as sd
            import soundfile as sf
            
            def read_audio():
                return sf.read(file_path)
                
            data, samplerate = await loop.run_in_executor(None, read_audio)
            
            def play_sd():
                sd.play(data, samplerate)
                sd.wait()
                
            await loop.run_in_executor(None, play_sd)
            return
        except ImportError:
            pass  # sounddevice not installed, try subprocess
        except Exception as e:
            logger.warning("sounddevice playback failed: %s", e)

        # Subprocess fallback
        try:
            import platform
            system = platform.system()
            import subprocess
            
            def run_subprocess():
                if system == "Darwin":
                    subprocess.run(["afplay", file_path], check=True, timeout=30)
                elif system == "Linux":
                    subprocess.run(["aplay", file_path], check=True, timeout=30)
                else:
                    subprocess.run([
                        "powershell", "-c",
                        f"(New-Object Media.SoundPlayer '{file_path}').PlaySync()"
                    ], check=True, timeout=30)
                    
            await loop.run_in_executor(None, run_subprocess)
        except Exception as e:
            logger.error("Audio playback failed entirely: %s — text was: %s", e, file_path)

    async def speak_bridging_phrase(self, task_type: str) -> None:
        """
        Immediately speak a bridging phrase while a specialist model loads.
        """
        BRIDGING_PHRASES = {
            "code": "A complex development task, Sir. Give me just a moment to pull up my developer environment.",
            "file": "Accessing your file system now, Sir. One moment.",
            "browser": "Opening a browser session for you, Sir. I will have that ready shortly.",
            "research": "Pulling up relevant sources, Sir. Conducting a search now.",
            "screen": "Taking control of the screen, Sir. Please stand by.",
            "analysis": "This will require some thought, Sir. I am analyzing the full context now.",
            "model_swap": "Switching my specialist module for this task, Sir. Just a moment.",
            "memory": "Consulting my memory archives, Sir. One moment.",
            "system": "Accessing system controls, Sir. Stand by.",
            "communication": "Accessing your communications, Sir. One moment.",
        }
        phrase = BRIDGING_PHRASES.get(
            task_type,
            "One moment, Sir. Engaging the appropriate specialist now."
        )
        await self.speak(phrase, urgent=True)

    def get_status(self) -> dict:
        ref_path = Path(os.path.expanduser(self.voice_ref_file))
        return {
            "f5tts_available": self._f5tts_available,
            "chatterbox_available": self._chatterbox_available,
            "kokoro_available": self._kokoro_available,
            "voice_ref_file_exists": ref_path.exists(),
            "active_engine": self._select_engine("en", False),
            "audio_output_dir": str(self._audio_output_dir),
        }

_instance: Optional[TTSEngine] = None

def get_tts_engine() -> TTSEngine:
    global _instance
    if _instance is None:
        _instance = TTSEngine()
    return _instance
