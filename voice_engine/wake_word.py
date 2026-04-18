"""
J.A.R.V.I.S. — voice_engine/wake_word.py
Always-on wake word detection using openWakeWord.
Listens for "Hey Jarvis" at ~0.5% CPU usage continuously.
On detection: triggers STT recording and agent pipeline.

Author: Hitansu Parichha | Nisum Technologies
Phase 3 — Blueprint v5.0
"""

import logging
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

class WakeWordDetector:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.wake_word = os.environ.get("WAKE_WORD", "Hey Jarvis")
        self._detection_threshold = float(os.environ.get("WAKE_WORD_THRESHOLD", "0.5"))
        
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._oww_available = False
        self._oww_model = None
        
        self._chunk_size = 1280
        self._sample_rate = 16000
        self._cooldown_seconds = 2.0
        self._last_detection = 0.0
        
        # Test availability without fully loading inference engines
        try:
            import openwakeword
        except ImportError:
            pass
            
        logger.info(
            "WakeWordDetector initialized — threshold=%.2f, word='%s'",
            self._detection_threshold, self.wake_word
        )

    def _try_init_oww(self) -> bool:
        """
        Initialize openWakeWord model for "Hey Jarvis" detection.
        Called when start() is invoked, not in __init__ (lazy init).
        """
        try:
            from openwakeword.model import Model
            try:
                self._oww_model = Model(
                    wakeword_models=["hey_jarvis"],
                    inference_framework="onnx"
                )
                logger.info("openWakeWord loaded — listening for '%s'", self.wake_word)
                self._oww_available = True
                return True
            except Exception:
                logger.warning(
                    "openWakeWord 'hey_jarvis' model not found. "
                    "Run: python3 -m openwakeword.train to create a custom model. "
                    "Wake word detection will be SIMULATED in Phase 3."
                )
                self._oww_available = False
                return False
        except ImportError:
            logger.warning("openwakeword not installed. Wake word detection unavailable.")
            self._oww_available = False
            return False

    def start(self) -> None:
        """
        Start the background wake word detection thread.
        If openWakeWord is not available, starts a SIMULATION thread instead.
        """
        if self._running:
            logger.warning("WakeWordDetector already running.")
            return

        self._running = True
        oww_ready = self._try_init_oww()

        if oww_ready:
            self._thread = threading.Thread(
                target=self._detection_loop,
                name="JarvisWakeWordDetector",
                daemon=True
            )
        else:
            self._thread = threading.Thread(
                target=self._simulation_loop,
                name="JarvisWakeWordSimulator",
                daemon=True
            )

        self._thread.start()
        logger.info(
            "Wake word detector started (%s mode).",
            "real" if oww_ready else "simulation"
        )

    def pause(self) -> None:
        """Pause mic listening so STT VAD can open its own InputStream."""
        self._paused = True

    def resume(self) -> None:
        """Resume mic listening after STT VAD is done."""
        self._paused = False

    def _detection_loop(self) -> None:
        """
        Real openWakeWord detection loop.
        Reads from microphone in chunks, feeds to OWW model,
        triggers callback on detection above threshold.
        Supports pause/resume so STT can take over the mic without conflict.
        """
        try:
            import sounddevice as sd
            import numpy as np

            while self._running:
                # If paused, yield mic and wait
                if self._paused:
                    import time as _t
                    _t.sleep(0.1)
                    continue

                try:
                    with sd.InputStream(
                        samplerate=self._sample_rate,
                        channels=1,
                        dtype="int16",
                        blocksize=self._chunk_size,
                    ) as stream:
                        logger.info("Microphone open — listening for '%s'...", self.wake_word)
                        while self._running and not self._paused:
                            audio_chunk, _ = stream.read(self._chunk_size)
                            audio_flat = audio_chunk.flatten()

                            prediction = self._oww_model.predict(audio_flat)
                            for model_name, score in prediction.items():
                                if score > self._detection_threshold:
                                    now = time.time()
                                    if now - self._last_detection > self._cooldown_seconds:
                                        self._last_detection = now
                                        logger.info(
                                            "Wake word detected! model=%s score=%.3f",
                                            model_name, score
                                        )
                                        threading.Thread(
                                            target=self.callback,
                                            daemon=True,
                                            name="WakeWordCallback"
                                        ).start()

                except Exception as e:
                    if self._running and not self._paused:
                        logger.error("Wake word detection error: %s", e)
                    import time as _t
                    _t.sleep(0.5)

        except ImportError:
            logger.error("sounddevice not available — microphone detection failed.")
        except Exception as e:
            logger.error("Wake word detection loop error: %s", e)
            self._running = False

    def _simulation_loop(self) -> None:
        """
        Simulation loop when openWakeWord is not available.
        Logs instructions every 30 seconds.
        """
        count = 0
        while self._running:
            time.sleep(30)
            count += 1
            if count == 1:
                logger.info(
                    "Wake word SIMULATION active. "
                    "Trigger manually: POST http://localhost:8000/voice/wake "
                    "Or say 'Hey Jarvis' via: POST /voice/listen"
                )

    def stop(self) -> None:
        """Stop the wake word detection thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            try:
                # Use a very short join so tests don't hang if time.sleep is blocking
                # The prompt asks for 2.0 second timeout. We might use 0.1 for faster tests but let's stick to 2.0.
                self._thread.join(timeout=2.0)
            except RuntimeError:
                pass
        logger.info("Wake word detector stopped.")

    def get_status(self) -> dict:
        """Return wake word detector status."""
        return {
            "running": self._running,
            "oww_available": self._oww_available,
            "mode": "real" if self._oww_available else "simulation",
            "wake_word": self.wake_word,
            "detection_threshold": self._detection_threshold,
            "cooldown_seconds": self._cooldown_seconds,
        }

_instance: Optional[WakeWordDetector] = None

def get_wake_word_detector(callback: Callable = None) -> WakeWordDetector:
    global _instance
    if _instance is None:
        if callback is None:
            def noop_callback(): pass
            callback = noop_callback
        _instance = WakeWordDetector(callback)
    return _instance
