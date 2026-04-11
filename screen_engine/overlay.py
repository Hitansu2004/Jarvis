"""
J.A.R.V.I.S. — screen_engine/overlay.py
Glowing screen border overlay stub. Full implementation in Phase 6.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import logging
import os
import platform

logger = logging.getLogger(__name__)

_OVERLAY_COLOR = os.getenv("JARVIS_OVERLAY_COLOR", "#FF0000")


class ScreenOverlay:
    """
    JARVIS screen border overlay.

    Displays a glowing red border around the screen when JARVIS has active
    control, visually indicating to the user that the system is acting autonomously.

    Phase 1 stub: prints console messages.
    Phase 6 will use pyobjc (macOS), tkinter (Windows), or python-xlib (Linux).
    """

    def show(self, color: str = _OVERLAY_COLOR) -> None:
        """
        Display the overlay border in the specified color.

        Args:
            color: Hex color string for the border (default: JARVIS_OVERLAY_COLOR env var).
        """
        system = platform.system()
        logger.info("OVERLAY SHOW — color=%s, platform=%s (stub).", color, system)
        print(f"[OVERLAY: JARVIS ACTIVE] — border color: {color}")
        # Phase 6 implementation:
        # macOS  → pyobjc-framework-Cocoa overlay window
        # Windows → tkinter borderless overlay
        # Linux  → python-xlib transparent overlay

    def hide(self) -> None:
        """
        Remove the overlay border from the screen.
        """
        logger.info("OVERLAY HIDE (stub).")
        print("[OVERLAY: HIDDEN]")

    def pulse(self) -> None:
        """
        Animate the overlay border with a pulsing effect.

        Phase 6 will implement a smooth opacity animation.
        """
        logger.info("OVERLAY PULSE (stub).")
        print("[OVERLAY: PULSING]")
