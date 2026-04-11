"""
J.A.R.V.I.S. — screen_engine/vision.py
Screen capture and vision model stub. Full implementation in Phase 5.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class ScreenVision:
    """
    Screen capture and visual understanding for J.A.R.V.I.S.

    Phase 1 stub: returns placeholder descriptions.
    Phase 5 will activate live screenshot capture via mss and
    vision model inference via Ollama (Gemma 4 E4B / 26B).
    """

    def __init__(self) -> None:
        """Initialise ScreenVision, checking for the mss library."""
        self._mss_available = False
        self._try_import_mss()

    def _try_import_mss(self) -> None:
        """Attempt to import mss for screen capture."""
        try:
            import mss  # noqa: F401
            self._mss_available = True
            logger.info("mss screen capture library available.")
        except ImportError:
            logger.warning(
                "mss not installed — screen capture unavailable. "
                "Install with: pip install mss"
            )

    async def capture_and_describe(self, deep: bool = False) -> dict:
        """
        Capture the current screen and return a visual description.

        Args:
            deep: If False, uses gemma4:e4b (passive, fast).
                  If True, uses gemma4:26b (deep, detailed analysis).

        Returns:
            dict with description (str), app_detected (str), context (str),
            timestamp (str), screenshot_b64 (str).
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        model_label = "gemma4:26b (deep)" if deep else "gemma4:e4b (passive)"

        if not self._mss_available:
            logger.info("Screen capture stub called (mss unavailable) — deep=%s.", deep)
            return {
                "description": (
                    "Screen capture is not yet active, Sir. "
                    "Phase 5 will enable live visual understanding using "
                    f"{model_label}."
                ),
                "app_detected": "unknown",
                "context": "Phase 5 stub",
                "timestamp": timestamp,
                "screenshot_b64": "",
            }

        # Phase 5 implementation will replace this block:
        screenshot_bytes = await self.capture_screenshot()
        encoded = base64.b64encode(screenshot_bytes).decode("utf-8") if screenshot_bytes else ""

        return {
            "description": (
                "Screen captured successfully, Sir. "
                "Visual analysis will be active in Phase 5."
            ),
            "app_detected": "unknown",
            "context": "Phase 5 vision stub — capture only, no inference yet.",
            "timestamp": timestamp,
            "screenshot_b64": encoded,
        }

    async def capture_screenshot(self) -> bytes:
        """
        Capture a raw screenshot of the primary monitor.

        Returns:
            Raw PNG bytes of the screenshot, or empty bytes if unavailable.
        """
        if not self._mss_available:
            return b""

        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                screenshot = sct.grab(monitor)
                return mss.tools.to_png(screenshot.rgb, screenshot.size)
        except Exception as exc:  # noqa: BLE001
            logger.error("Screenshot capture failed: %s", exc)
            return b""
