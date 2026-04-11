"""
J.A.R.V.I.S. — screen_engine/control.py
Screen/keyboard/mouse control stub with mutex locking. Full implementation in Phase 6.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_AUDIT_LOG = Path(__file__).parent.parent / "sandbox" / "audit.log"


def _write_audit(entry: dict) -> None:
    """Write a single audit log entry."""
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write audit log: %s", exc)


class ScreenController:
    """
    Screen and input control manager for J.A.R.V.I.S.

    Maintains a mutex lock so only one agent can control the screen at a time.
    Phase 1 stub: all execute_action calls return a stub response.
    Phase 6 will activate pyautogui-based real control.
    """

    def __init__(self) -> None:
        """Initialise controller with unlocked mutex."""
        self.mutex_locked: bool = False
        self.current_agent: Optional[str] = None
        self.pending_actions: list[dict] = []

    async def acquire_control(self, agent_name: str) -> bool:
        """
        Attempt to acquire exclusive screen control for an agent.

        Args:
            agent_name: The name of the agent requesting control.

        Returns:
            True if control was acquired, False if another agent holds the lock.
        """
        if self.mutex_locked:
            logger.warning(
                "Control request by '%s' denied — '%s' currently holds the lock.",
                agent_name,
                self.current_agent,
            )
            return False

        self.mutex_locked = True
        self.current_agent = agent_name

        # Show overlay (Phase 1: stub)
        from screen_engine.overlay import ScreenOverlay
        ScreenOverlay().show()

        _write_audit({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": agent_name,
            "model_used": "none",
            "action_type": "CONTROL_ACQUIRED",
            "command_or_url": f"acquire_control by {agent_name}",
            "confirmation_status": "AUTO_APPROVED",
            "outcome": "SUCCESS",
            "error_message": None,
        })
        logger.info("Screen control acquired by agent: %s", agent_name)
        return True

    async def release_control(self) -> None:
        """
        Release screen control and hide the overlay.

        Clears pending_actions queue and restores control to the user.
        """
        agent = self.current_agent
        self.mutex_locked = False
        self.current_agent = None
        self.pending_actions.clear()

        # Hide overlay (Phase 1: stub)
        from screen_engine.overlay import ScreenOverlay
        ScreenOverlay().hide()

        _write_audit({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": agent or "unknown",
            "model_used": "none",
            "action_type": "CONTROL_RELEASED",
            "command_or_url": "release_control",
            "confirmation_status": "AUTO_APPROVED",
            "outcome": "SUCCESS",
            "error_message": None,
        })

        logger.info("Screen control released — returned to user.")
        print("[JARVIS]: Control returned to you, Sir.")

    async def execute_action(self, action: dict) -> dict:
        """
        Execute a single screen control action.

        Must hold the mutex lock before calling this method.

        Args:
            action: Action definition dict with at minimum a "type" key.

        Returns:
            dict with status and the original action.

        Raises:
            RuntimeError: If called without holding the control lock.
        """
        if not self.mutex_locked:
            raise RuntimeError(
                "Cannot execute action without first acquiring the control lock. "
                "Call acquire_control() before execute_action()."
            )

        _write_audit({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": self.current_agent or "unknown",
            "model_used": "none",
            "action_type": "SCREEN_ACTION",
            "command_or_url": str(action),
            "confirmation_status": "CONFIRMED",
            "outcome": "SUCCESS",
            "error_message": None,
        })

        logger.info("Screen action (stub): %s", action)
        # Phase 6 will replace this with actual pyautogui calls
        return {"status": "stub", "action": action}
