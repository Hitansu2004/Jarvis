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

    async def capture_and_describe(
        self,
        deep: bool = False,
        mode_manager = None,
        agent_registry = None,
    ) -> dict:
        """
        Capture the current screen and return a structured visual description.

        Uses Gemma 4 E4B for passive/fast analysis (deep=False) or
        Gemma 4 26B-A4B for deep analysis (deep=True).

        Requires mode_manager and agent_registry to be passed in from the gateway.
        Both default to None for backward compatibility with tests.

        Args:
            deep: If False, uses screen_vision_passive agent (gemma4:e4b).
                  If True, uses screen_vision_deep agent (gemma4:26b).
            mode_manager: ModeManager singleton from gateway.
            agent_registry: AgentRegistry singleton from gateway.

        Returns:
            dict with keys:
              description (str)  — human-readable description of screen
              app_detected (str) — primary app: vscode/browser/terminal/finder/other
              context (str)      — brief context: "TypeScript file auth.ts line 26"
              suggestions (list) — list of suggested actions (may be empty)
              timestamp (str)    — ISO 8601 UTC timestamp
              screenshot_b64 (str) — base64 PNG (empty if capture failed)
              deep (bool)        — whether deep model was used
              model_used (str)   — actual model used
        """
        import asyncio
        timestamp = datetime.now(timezone.utc).isoformat()

        # Capture screenshot
        screenshot_bytes = await self.capture_screenshot()
        encoded = ""
        if screenshot_bytes:
            encoded = base64.b64encode(screenshot_bytes).decode("utf-8")

        if not screenshot_bytes:
            return {
                "description": "Screen capture unavailable, Sir. mss library may not be installed.",
                "app_detected": "unknown",
                "context": "capture_failed",
                "suggestions": [],
                "timestamp": timestamp,
                "screenshot_b64": "",
                "deep": deep,
                "model_used": "none",
            }

        # If no mode_manager, return basic capture-only result
        if mode_manager is None:
            return {
                "description": "Screen captured, Sir. Vision inference requires mode_manager.",
                "app_detected": "unknown",
                "context": "no_inference",
                "suggestions": [],
                "timestamp": timestamp,
                "screenshot_b64": encoded,
                "deep": deep,
                "model_used": "none",
            }

        # Select agent based on deep flag
        agent_name = "screen_vision_deep" if deep else "screen_vision_passive"

        # Get system prompt for the selected agent
        system_prompt = ""
        if agent_registry:
            system_prompt = agent_registry.get_system_prompt(agent_name)

        # Build the user message for vision analysis
        user_message = (
            "Analyze the current screen. Provide a structured response in this EXACT format:\n\n"
            "APP: <one of: vscode, browser, terminal, finder, slack, notion, figma, media_player, pdf_viewer, other>\n"
            "CONTEXT: <one sentence: what specifically is on screen, e.g. 'TypeScript file auth.ts, async function handleLogin at line 26'>\n"
            "DESCRIPTION: <2-3 sentences describing what the user appears to be doing>\n"
            "SUGGESTION: <ONE specific, actionable suggestion OR 'none' if nothing useful>\n\n"
            "Be concise and specific. Do not repeat information across sections."
        )

        try:
            result = await mode_manager.complete(
                agent_name=agent_name,
                system_prompt=system_prompt,
                user_message=user_message,
                complexity_score=3 if not deep else 6,
                images=[screenshot_bytes],
                temperature=0.2,
                max_tokens=512,
            )

            raw_response = result.get("content", "")
            model_used = result.get("model_used", "unknown")

            # Parse the structured response
            parsed = self._parse_vision_response(raw_response)

            return {
                "description": parsed["description"],
                "app_detected": parsed["app"],
                "context": parsed["context"],
                "suggestions": [parsed["suggestion"]] if parsed["suggestion"] != "none" else [],
                "timestamp": timestamp,
                "screenshot_b64": encoded if deep else "",  # Only include in deep mode
                "deep": deep,
                "model_used": model_used,
                "raw_response": raw_response,
            }

        except Exception as exc:
            logger.error("Vision inference failed: %s", exc)
            return {
                "description": f"Vision inference failed, Sir: {exc}",
                "app_detected": "unknown",
                "context": "inference_error",
                "suggestions": [],
                "timestamp": timestamp,
                "screenshot_b64": encoded,
                "deep": deep,
                "model_used": "error",
            }

    def _parse_vision_response(self, raw: str) -> dict:
        """
        Parse the structured vision response from the LLM.
        Returns dict with app, context, description, suggestion.
        """
        result = {
            "app": "other",
            "context": "",
            "description": raw,
            "suggestion": "none",
        }

        lines = raw.strip().split("\n")
        description_lines = []

        for line in lines:
            line = line.strip()
            if line.startswith("APP:"):
                app_raw = line[4:].strip().lower()
                # Normalize app names
                app_map = {
                    "vscode": "vscode", "vs code": "vscode", "visual studio code": "vscode",
                    "browser": "browser", "chrome": "browser", "safari": "browser",
                    "firefox": "browser", "edge": "browser",
                    "terminal": "terminal", "iterm": "terminal", "iterm2": "terminal",
                    "finder": "finder", "file explorer": "finder",
                    "slack": "slack", "notion": "notion", "figma": "figma",
                    "media_player": "media_player", "vlc": "media_player",
                    "pdf_viewer": "pdf_viewer", "preview": "pdf_viewer",
                }
                result["app"] = app_map.get(app_raw, app_raw if app_raw else "other")
            elif line.startswith("CONTEXT:"):
                result["context"] = line[8:].strip()
            elif line.startswith("DESCRIPTION:"):
                result["description"] = line[12:].strip()
            elif line.startswith("SUGGESTION:"):
                sugg = line[11:].strip()
                result["suggestion"] = "none" if sugg.lower() in ("none", "n/a", "-", "") else sugg

        # Fallback: if description is still the raw response, use it
        if result["description"] == raw and description_lines:
            result["description"] = " ".join(description_lines)

        return result

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

_vision_instance: Optional[ScreenVision] = None

def get_screen_vision() -> ScreenVision:
    global _vision_instance
    if _vision_instance is None:
        _vision_instance = ScreenVision()
    return _vision_instance
