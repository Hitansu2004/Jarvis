"""
J.A.R.V.I.S. — voice_engine/tts.py
Text-to-Speech engine using Kokoro ONNX.
- Fast (~1-2 seconds per response)
- Premium female voice (af_heart)
- Hindi + English + Hinglish support
- Full response generated & concatenated before playback (no stuttering)

Author: Hitansu Parichha | Nisum Technologies
Phase 3 — Blueprint v5.0
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Voice selection — premium female options:
#   af_heart  = American Female, warm & natural  ← DEFAULT
#   af_nova   = American Female, crisp & clear
#   af_bella  = American Female, expressive
#   af_sarah  = American Female, calm
#   bf_emma   = British Female, elegant
#   hf_alpha  = Hindi Female (for Hindi-heavy responses)
# Dual voice model:
#   af_heart  = American Female, warm & natural          ← English default
#   hf_alpha  = Hindi Female, native Devanagari speaker  ← Hindi default
VOICE_EN = os.environ.get("TTS_VOICE_EN", "af_heart")
VOICE_HI = os.environ.get("TTS_VOICE_HI", "hf_alpha")
KOKORO_SPEED = float(os.environ.get("TTS_SPEED", "1.05"))

# Markdown / symbol cleanup patterns (compiled once at import time)
_JARVIS_ABBR = re.compile(r'J\.A\.R\.V\.I\.S\.?')
_BOLD        = re.compile(r'\*\*(.+?)\*\*', re.DOTALL)
_ITALIC      = re.compile(r'\*(.+?)\*', re.DOTALL)
_HEADERS     = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_CODE_BLOCK  = re.compile(r'```.*?```', re.DOTALL)
_INLINE_CODE = re.compile(r'`(.+?)`')
_BULLETS     = re.compile(r'^[-•·\*]\s+', re.MULTILINE)
_NUMBERED    = re.compile(r'^\d+\.\s+', re.MULTILINE)
_MULTI_NL    = re.compile(r'\n{3,}')
_MULTI_SP    = re.compile(r'  +')


class TTSEngine:
    def __init__(self):
        self._kokoro_pipeline = None
        self._kokoro_available = False

        current_dir = Path(__file__).parent
        self._audio_output_dir = current_dir / "audio_output"
        self._audio_output_dir.mkdir(parents=True, exist_ok=True)

        self._sentence_pattern = re.compile(r'(?<=[.!?])\s+')

        self._try_load_kokoro()

        logger.info(
            "TTS initialized. Kokoro: %s | EN voice: %s | HI voice: %s",
            self._kokoro_available, VOICE_EN, VOICE_HI
        )

    def _try_load_kokoro(self) -> None:
        try:
            from kokoro_onnx import Kokoro
            self._kokoro_pipeline = Kokoro("kokoro-v0_19.onnx", "voices.bin")
            self._kokoro_available = True
            logger.info("Kokoro TTS loaded successfully.")
        except ImportError:
            logger.warning("kokoro-onnx not installed. TTS unavailable.")
            self._kokoro_available = False
        except Exception as e:
            logger.warning("Failed to load Kokoro TTS: %s", e)
            self._kokoro_available = False

    def _clean_for_speech(self, text: str) -> str:
        """
        Strip markdown and fix abbreviations before TTS synthesis.
        - J.A.R.V.I.S. → Jarvis
        - **bold** / *italic* → plain text
        - # Heading → plain text
        - Numbered lists, bullet points → removed
        - Em-dashes (—) → comma pause
        - Backtick code → plain text
        """
        t = _JARVIS_ABBR.sub('Jarvis', text)
        t = _CODE_BLOCK.sub('', t)          # remove code blocks
        t = _BOLD.sub(r'\1', t)             # **text** → text
        t = _ITALIC.sub(r'\1', t)           # *text* → text
        t = _HEADERS.sub('', t)             # ## heading → heading
        t = _INLINE_CODE.sub(r'\1', t)     # `code` → code
        t = _BULLETS.sub('', t)             # - bullet → bullet
        t = _NUMBERED.sub('', t)            # 1. item → item
        t = t.replace('—', ', ').replace('–', ', ')
        t = t.replace('*', '').replace('#', '')
        t = _MULTI_NL.sub('\n\n', t)
        t = _MULTI_SP.sub(' ', t)
        return t.strip()

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences for separate generation, then stitch."""
        lines = text.split('\n')
        sentences = []
        for line in lines:
            parts = self._sentence_pattern.split(line)
            for part in parts:
                cleaned = part.strip()
                if len(cleaned) >= 3:
                    sentences.append(cleaned)
        return sentences

    def _detect_language(self, text: str) -> tuple[str, str]:
        """
        Detect if text is Hindi, English, or Hinglish.
        Returns (kokoro_lang, kokoro_voice).
        - Pure Hindi (Devanagari > 30%) → ('hi', VOICE_HI)
        - English / Hinglish             → ('en-us', VOICE_EN)
        """
        devanagari_chars = sum(1 for c in text if '\u0900' <= c <= '\u097F')
        ratio = devanagari_chars / max(len(text), 1)
        if ratio > 0.3:
            return "hi", VOICE_HI
        return "en-us", VOICE_EN

    async def speak(self, text: str, language: str = "auto", urgent: bool = False) -> bool:
        """
        Speak text aloud.
        - Cleans markdown/symbols before synthesis
        - Uses af_heart (English) or hf_alpha (Hindi) automatically per sentence
        - Concatenates all audio into ONE smooth clip played via afplay
        """
        if not text or not text.strip():
            return False

        # Strip markdown symbols before synthesis
        text = self._clean_for_speech(text)

        if not self._kokoro_available:
            print(f"[JARVIS]: {text}")
            return True

        try:
            import numpy as np
            import soundfile as sf
            import subprocess

            sentences = self._split_sentences(text)
            if not sentences:
                return False

            loop = asyncio.get_event_loop()
            all_segments = []
            sample_rate = 24000

            for sentence in sentences:
                # Auto-detect language AND voice per sentence
                if language in ("auto", "en"):
                    lang_param, voice = self._detect_language(sentence)
                elif language == "hi":
                    lang_param, voice = "hi", VOICE_HI
                else:
                    lang_param, voice = "en-us", VOICE_EN

                def generate(s=sentence, lang=lang_param, v=voice):
                    return self._kokoro_pipeline.create(
                        s,
                        voice=v,
                        speed=KOKORO_SPEED,
                        lang=lang,
                    )

                samples, sr = await loop.run_in_executor(None, generate)
                sample_rate = sr
                all_segments.append(samples)

            if not all_segments:
                return False

            # Concatenate ALL sentences into ONE audio stream — no gaps, no stutter
            combined = np.concatenate(all_segments)

            # Save to file and use afplay (macOS native) — avoids PortAudio mic conflict
            out_file = self._audio_output_dir / "jarvis_response.wav"

            def save_and_play():
                sf.write(str(out_file), combined, sample_rate)
                subprocess.run(
                    ["afplay", str(out_file)],
                    check=True,
                    timeout=120
                )

            await loop.run_in_executor(None, save_and_play)
            return True

        except Exception as e:
            logger.error("TTS speak failed: %s", e)
            print(f"[JARVIS]: {text}")
            return True


    async def _afplay_fallback(self, text: str) -> bool:
        """macOS afplay fallback using soundfile."""
        try:
            import numpy as np
            import soundfile as sf
            import subprocess

            loop = asyncio.get_event_loop()
            sentences = self._split_sentences(text)
            all_segments = []
            sample_rate = 24000

            for sentence in sentences:
                lang_param = self._detect_language(sentence)

                def generate(s=sentence, lang=lang_param):
                    return self._kokoro_pipeline.create(
                        s, voice=KOKORO_VOICE, speed=KOKORO_SPEED, lang=lang
                    )

                samples, sr = await loop.run_in_executor(None, generate)
                sample_rate = sr
                all_segments.append(samples)

            combined = np.concatenate(all_segments)
            out_file = self._audio_output_dir / "jarvis_response.wav"

            def save_and_play():
                sf.write(str(out_file), combined, sample_rate)
                subprocess.run(["afplay", str(out_file)], check=True, timeout=120)

            await loop.run_in_executor(None, save_and_play)
            return True
        except Exception as e:
            logger.error("afplay fallback failed: %s", e)
            print(f"[JARVIS]: {text}")
            return True

    def get_status(self) -> dict:
        """Return TTS engine status."""
        return {
            "active_engine": "kokoro" if self._kokoro_available else "console",
            "kokoro_available": self._kokoro_available,
            "voice_en": VOICE_EN,
            "voice_hi": VOICE_HI,
            "speed": KOKORO_SPEED,
        }

    async def speak_bridging_phrase(self, task_type: str) -> None:
        """Speak a quick bridging phrase while processing."""
        BRIDGING_PHRASES = {
            "code": "Working on it, Sir.",
            "file": "Accessing your file system.",
            "browser": "Opening a browser session.",
            "research": "Searching now, Sir.",
            "default": "One moment, Sir.",
        }
        phrase = BRIDGING_PHRASES.get(task_type, BRIDGING_PHRASES["default"])
        await self.speak(phrase)


# Singleton
_instance: Optional[TTSEngine] = None

def get_tts_engine() -> TTSEngine:
    global _instance
    if _instance is None:
        _instance = TTSEngine()
    return _instance
