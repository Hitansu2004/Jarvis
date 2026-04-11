"""
J.A.R.V.I.S. — sandbox/executor.py
Sandboxed subprocess executor with security policy enforcement.
Full audit logging. Phase 2 will add real enforcement; Phase 1 builds the skeleton.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

_SECURITY_POLICY_PATH = Path(__file__).parent / "jarvis_security.yaml"
_AUDIT_LOG_PATH = Path(__file__).parent / "audit.log"


class SecurityError(Exception):
    """Raised when a command violates the JARVIS security policy."""


def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _load_policy() -> dict:
    """
    Load the JARVIS security policy from jarvis_security.yaml.

    Returns:
        Security policy dict, or empty dict if file is unavailable.
    """
    try:
        with _SECURITY_POLICY_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.warning("Security policy file not found at %s.", _SECURITY_POLICY_PATH)
        return {}
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load security policy: %s", exc)
        return {}


def _write_audit(entry: dict) -> None:
    """
    Append a single JSON line to sandbox/audit.log.

    Args:
        entry: Dict to serialise as a JSON-Lines entry.
    """
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write audit log: %s", exc)


class Executor:
    """
    Sandboxed command executor for J.A.R.V.I.S.

    Checks every command against the security policy before execution.
    Logs all actions (approved, rejected, pending) to audit.log.

    Phase 2 will add full network and path enforcement.
    Phase 1 provides the correct interface and blocking for the most
    critical security rules (blocked_prefixes, double-confirmation).
    """

    def __init__(self) -> None:
        """Load the security policy on initialisation."""
        self.policy: dict = _load_policy()
        self._pending_confirmations: dict[str, dict] = {}

    def execute(
        self,
        command: str,
        action_type: str,
        agent_name: str,
        confirmed: bool = False,
    ) -> dict:
        """
        Execute a command after security policy validation.

        Args:
            command: Shell command string to execute.
            action_type: Category of action (e.g. FILE_DELETE, CHAT, HTTP_REQUEST).
            agent_name: Name of the agent requesting the action.
            confirmed: True if the user has explicitly confirmed a double-confirm action.

        Returns:
            dict with status ("success"|"failed"|"rejected"|"needs_confirmation"),
            output (str), error (str|None).
        """
        # --- Step 1: Check blocked command prefixes ---
        blocked_prefixes = self.policy.get("commands", {}).get("blocked_prefixes", [])
        for prefix in blocked_prefixes:
            if command.strip().startswith(prefix):
                error_msg = f"SecurityError: Command blocked by policy — starts with '{prefix}'."
                _write_audit({
                    "timestamp": _iso_now(),
                    "agent_name": agent_name,
                    "model_used": "none",
                    "action_type": action_type,
                    "command_or_url": command[:200],
                    "confirmation_status": "DENIED",
                    "outcome": "BLOCKED",
                    "error_message": error_msg,
                })
                raise SecurityError(error_msg)

        # --- Step 2: Check blocked paths ---
        blocked_paths = self.policy.get("paths", {}).get("blocked", [])
        for blocked in blocked_paths:
            expanded = os.path.expanduser(blocked)
            if expanded in command or blocked in command:
                error_msg = f"SecurityError: Access to blocked path '{blocked}' denied."
                _write_audit({
                    "timestamp": _iso_now(),
                    "agent_name": agent_name,
                    "model_used": "none",
                    "action_type": action_type,
                    "command_or_url": command[:200],
                    "confirmation_status": "DENIED",
                    "outcome": "BLOCKED",
                    "error_message": error_msg,
                })
                raise SecurityError(error_msg)

        # --- Step 3: Check confirmation requirements ---
        always_required: list[str] = self.policy.get("confirmations", {}).get("always_required", [])
        double_required: list[str] = self.policy.get("confirmations", {}).get("double_confirmation_required", [])

        if action_type in always_required and not confirmed:
            confirmation_key = f"{agent_name}:{action_type}:{hash(command)}"
            self._pending_confirmations[confirmation_key] = {
                "command": command,
                "agent_name": agent_name,
                "action_type": action_type,
            }
            _write_audit({
                "timestamp": _iso_now(),
                "agent_name": agent_name,
                "model_used": "none",
                "action_type": action_type,
                "command_or_url": command[:200],
                "confirmation_status": "PENDING",
                "outcome": "PARTIAL",
                "error_message": None,
            })
            msg = (
                f"This action requires your confirmation, Sir: {action_type}.\n"
                f"Command: {command[:120]}\n"
                "Please confirm to proceed."
            )
            if action_type in double_required:
                msg = (
                    f"⚠️  DOUBLE CONFIRMATION REQUIRED for {action_type}, Sir.\n"
                    f"Command: {command[:120]}\n"
                    "This action is irreversible. Please confirm TWICE to proceed."
                )
            return {
                "status": "needs_confirmation",
                "command": command,
                "message": msg,
                "error": None,
            }

        # --- Step 4: Execute via subprocess ---
        _write_audit({
            "timestamp": _iso_now(),
            "agent_name": agent_name,
            "model_used": "none",
            "action_type": action_type,
            "command_or_url": command[:200],
            "confirmation_status": "CONFIRMED" if confirmed else "AUTO_APPROVED",
            "outcome": "SUCCESS",
            "error_message": None,
        })

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            outcome = "SUCCESS" if result.returncode == 0 else "FAILURE"
            error_str = result.stderr.strip() if result.stderr else None

            # Update audit with final outcome
            _write_audit({
                "timestamp": _iso_now(),
                "agent_name": agent_name,
                "model_used": "none",
                "action_type": action_type,
                "command_or_url": command[:200],
                "confirmation_status": "CONFIRMED" if confirmed else "AUTO_APPROVED",
                "outcome": outcome,
                "error_message": error_str,
            })

            return {
                "status": "success" if result.returncode == 0 else "failed",
                "output": result.stdout.strip(),
                "error": error_str,
            }

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after 30 seconds: {command[:80]}"
            logger.error(error_msg)
            _write_audit({
                "timestamp": _iso_now(),
                "agent_name": agent_name,
                "model_used": "none",
                "action_type": action_type,
                "command_or_url": command[:200],
                "confirmation_status": "AUTO_APPROVED",
                "outcome": "FAILURE",
                "error_message": error_msg,
            })
            return {"status": "failed", "output": "", "error": error_msg}

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            logger.error("Executor error: %s", error_msg)
            return {"status": "failed", "output": "", "error": error_msg}
