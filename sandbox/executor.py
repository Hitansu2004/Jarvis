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

    GAP 4 FIX: Real 2-step double confirmation implemented.
    _pending_confirmations now tracks confirmations_received and required_confirmations.
    The confirm() method increments the counter and executes when satisfied.

    Phase 2 will add full network and path enforcement.
    Phase 1 provides the correct interface and blocking for the most
    critical security rules (blocked_prefixes, double-confirmation).
    """

    def __init__(self) -> None:
        """Load the security policy on initialisation."""
        self.policy: dict = _load_policy()
        # GAP 4 FIX: Each pending action now tracks confirmation stage
        # Structure: { confirmation_key: { command, agent_name, action_type,
        #              confirmations_received, required_confirmations } }
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
            output (str), error (str|None), and confirmation_key (str, if pending).
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
            # GAP 4 FIX: Track required vs received confirmations per action
            required_count = 2 if action_type in double_required else 1
            confirmation_key = f"{agent_name}:{action_type}:{hash(command)}"

            # Store pending action with staged confirmation tracking
            self._pending_confirmations[confirmation_key] = {
                "command": command,
                "agent_name": agent_name,
                "action_type": action_type,
                "confirmations_received": 0,         # ← track count
                "required_confirmations": required_count,
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

            if action_type in double_required:
                msg = (
                    f"⚠️  DOUBLE CONFIRMATION REQUIRED for {action_type}, Sir.\n"
                    f"Command: {command[:120]}\n"
                    "This action is irreversible. Please confirm TWICE to proceed.\n"
                    f"Confirmation key: {confirmation_key}"
                )
            else:
                msg = (
                    f"This action requires your confirmation, Sir: {action_type}.\n"
                    f"Command: {command[:120]}\n"
                    "Please confirm to proceed.\n"
                    f"Confirmation key: {confirmation_key}"
                )

            return {
                "status": "needs_confirmation",
                "confirmation_key": confirmation_key,   # ← caller must send this back
                "confirmations_received": 0,
                "required_confirmations": required_count,
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

    def confirm(self, confirmation_key: str) -> dict:
        """
        GAP 4 FIX: Submit one confirmation step for a pending action.

        For single-confirmation actions, one call executes the command.
        For double-confirmation actions (FILE_DELETE, PURCHASE), two calls are needed.

        Args:
            confirmation_key: The key returned in the needs_confirmation response.

        Returns:
            dict — either another needs_confirmation (if more steps required),
            or the final execution result dict.
        """
        pending = self._pending_confirmations.get(confirmation_key)
        if not pending:
            return {
                "status": "failed",
                "output": "",
                "error": f"No pending action found for key '{confirmation_key}'. It may have already been executed or cancelled.",
            }

        pending["confirmations_received"] += 1
        received = pending["confirmations_received"]
        required = pending["required_confirmations"]

        _write_audit({
            "timestamp": _iso_now(),
            "agent_name": pending["agent_name"],
            "model_used": "none",
            "action_type": pending["action_type"],
            "command_or_url": pending["command"][:200],
            "confirmation_status": f"CONFIRMED_{received}_OF_{required}",
            "outcome": "PARTIAL" if received < required else "SUCCESS",
            "error_message": None,
        })

        if received < required:
            # More confirmations needed — return intermediate state
            remaining = required - received
            return {
                "status": "needs_confirmation",
                "confirmation_key": confirmation_key,
                "confirmations_received": received,
                "required_confirmations": required,
                "message": (
                    f"Confirmation {received} of {required} received, Sir. "
                    f"Please confirm {remaining} more time(s) to proceed.\n"
                    f"Action: {pending['action_type']} — {pending['command'][:80]}"
                ),
                "error": None,
            }

        # All confirmations received — execute the command
        cmd = pending.pop("command")
        agent = pending.pop("agent_name")
        atype = pending.pop("action_type")
        del self._pending_confirmations[confirmation_key]

        logger.info(
            "Double confirmation satisfied (%d/%d) for %s — executing: %s",
            received, required, atype, cmd[:80],
        )
        return self.execute(command=cmd, action_type=atype, agent_name=agent, confirmed=True)

    def cancel(self, confirmation_key: str) -> dict:
        """
        Cancel a pending confirmation.

        Args:
            confirmation_key: The key of the pending action to cancel.

        Returns:
            dict with status "cancelled" or "not_found".
        """
        if confirmation_key in self._pending_confirmations:
            pending = self._pending_confirmations.pop(confirmation_key)
            _write_audit({
                "timestamp": _iso_now(),
                "agent_name": pending.get("agent_name", "unknown"),
                "model_used": "none",
                "action_type": pending.get("action_type", "unknown"),
                "command_or_url": pending.get("command", "")[:200],
                "confirmation_status": "CANCELLED",
                "outcome": "FAILURE",
                "error_message": "User cancelled the action.",
            })
            return {"status": "cancelled", "message": f"Action cancelled, Sir. Key: {confirmation_key}"}
        return {"status": "not_found", "error": f"No pending action found for key '{confirmation_key}'."}
