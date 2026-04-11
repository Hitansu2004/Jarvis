"""
J.A.R.V.I.S. — sandbox/security_enforcer.py
Central security orchestration layer. All security checks flow through here.
Coordinates PathGuard, NetworkGuard, and AuditManager.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

from sandbox.audit_manager import get_audit_manager
from sandbox.network_guard import NetworkGuard
from sandbox.path_guard import PathGuard

logger = logging.getLogger(__name__)

_SECURITY_POLICY_PATH = Path(__file__).parent / "jarvis_security.yaml"


class SecurityError(Exception):
    """Exception raised when a security violation occurs."""
    pass


@dataclass
class PendingAction:
    """Represents a multi-step action awaiting user confirmation."""
    confirmation_key: str
    command: str
    action_type: str
    agent_name: str
    path: Optional[str]
    url: Optional[str]
    file_preview: Optional[str]
    required_confirmations: int
    received_confirmations: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(init=False)

    def __post_init__(self):
        # 5 minutes expiry by default, will override if policy dictates
        self.expires_at = self.created_at + timedelta(seconds=300)

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


def _load_policy() -> dict:
    try:
        with _SECURITY_POLICY_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.warning("Security policy not found at %s.", _SECURITY_POLICY_PATH)
        return {}
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load security policy: %s", exc)
        return {}


class SecurityEnforcer:
    """
    Central security orchestration layer.
    """

    def __init__(self) -> None:
        """Initialize all security components from policy."""
        self._policy = _load_policy()

        self._path_guard = PathGuard(self._policy)
        self._network_guard = NetworkGuard(self._policy)
        self._audit = get_audit_manager()

        self._pending_confirmations: dict[str, PendingAction] = {}

        # Load security settings
        secs = self._policy.get("confirmations", {})
        self._always_confirm = set(secs.get("always_required", []))
        self._double_confirm = set(secs.get("double_confirmation_required", []))

        settings = self._policy.get("confirmation_settings", {})
        self._expiry_seconds = settings.get("expiry_seconds", 300)
        self._file_preview_chars = settings.get("file_preview_chars", 100)

        self._blocked_prefixes = set(self._policy.get("commands", {}).get("blocked_prefixes", []))
        self._print_alerts = self._policy.get("violations", {}).get("speak_alert", True)
        self._alert_prefix = self._policy.get("violations", {}).get("alert_prefix", "[JARVIS SECURITY]")

    def _extract_paths(self, command: str) -> list[str]:
        """Extract possible file paths from a shell command."""
        # Simple heuristic: words starting with / or ~/
        paths = []
        for word in command.split():
            # Stripping quotes that commands might use
            word = word.strip("\"'")
            if word.startswith("/") or word.startswith("~/"):
                paths.append(word)
        return paths

    def _read_file_preview(self, path: str) -> str:
        """Try to read the first N characters of a file."""
        import os
        expanded = os.path.expanduser(path)
        if not os.path.exists(expanded):
            return f"File not found: {path}"
        if not os.path.isfile(expanded):
            return f"Path is not a regular file: {path}"

        try:
            with open(expanded, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(self._file_preview_chars)
                if len(content) == self._file_preview_chars:
                    content += "..."
                return content
        except Exception as exc:  # noqa: BLE001
            return f"File not readable: {exc}"

    def report_violation(
        self,
        violation_type: str,
        agent_name: str,
        detail: str,
        model_used: str = "unknown"
    ) -> None:
        """Record and alert on a security violation."""
        message = f"{violation_type} — {detail}. Blocked."
        
        self._audit.write({
            "agent_name": agent_name,
            "model_used": model_used,
            "action_type": "SECURITY_VIOLATION",
            "command_or_url": detail,
            "outcome": "BLOCKED",
            "error_message": message,
            "risk_level": "blocked",
        })

        if self._print_alerts:
            print(f"\n{self._alert_prefix}: {message}\n")

    def check_command(
        self,
        command: str,
        action_type: str,
        agent_name: str,
        model_used: str = "unknown"
    ) -> dict:
        """
        Full security check for a shell command.
        """
        # PIPELINE 1: Blocked command prefixes
        for prefix in self._blocked_prefixes:
            if command.strip().startswith(prefix):
                self.report_violation(
                    "COMMAND_BLOCKED",
                    agent_name,
                    f"Command '{command}' matches blocked prefix '{prefix}'",
                    model_used,
                )
                return {
                    "allowed": False,
                    "status": "blocked",
                    "message": f"Command is blocked by security policy.",
                    "risk_level": "blocked"
                }

        # PIPELINE 2: Path extraction & Check
        paths = self._extract_paths(command)
        identified_risk = "safe"
        
        # Operation mapping - rough guess based on action_type
        operation = "read"
        if action_type in ("FILE_WRITE", "FILE_MOVE", "FILE_RENAME", "TERMINAL_CMD"):
            operation = "write"
        if action_type == "FILE_DELETE":
            operation = "delete"

        for path in paths:
            path_result = self._path_guard.validate(path, operation)
            if not path_result["allowed"]:
                self.report_violation(
                    path_result.get("reason", "PATH_BLOCKED"),
                    agent_name,
                    f"Path {path} accessed",
                    model_used,
                )
                return {
                    "allowed": False,
                    "status": "blocked",
                    "message": path_result["reason"],
                    "risk_level": "blocked"
                }
            if path_result["risk_level"] == "caution":
                identified_risk = "caution"

        # PIPELINE 3: Confirmation Requirements
        req_confirms = 0
        if action_type in self._always_confirm:
            req_confirms = 1
        if action_type in self._double_confirm:
            req_confirms = 2

        if req_confirms > 0:
            key = str(uuid.uuid4())
            file_preview = None
            extracted_path = paths[0] if paths else None

            # PIPELINE 4: file_preview for FILE_DELETE
            if action_type == "FILE_DELETE" and extracted_path:
                file_preview = self._read_file_preview(extracted_path)

            pending = PendingAction(
                confirmation_key=key,
                command=command,
                action_type=action_type,
                agent_name=agent_name,
                path=extracted_path,
                url=None,
                file_preview=file_preview,
                required_confirmations=req_confirms,
            )
            pending.expires_at = pending.created_at + timedelta(seconds=self._expiry_seconds)
            self._pending_confirmations[key] = pending

            self._audit.write({
                "agent_name": agent_name,
                "model_used": model_used,
                "action_type": action_type,
                "command_or_url": command,
                "confirmation_status": "PENDING",
                "outcome": "PARTIAL",
                "path_validated": True if paths else False,
            })

            return {
                "allowed": False,
                "status": "needs_confirmation",
                "confirmation_key": key,
                "required_confirmations": req_confirms,
                "received_confirmations": 0,
                "file_preview": file_preview,
                "message": f"Action {action_type} requires {req_confirms} confirmations.",
                "risk_level": "caution",
            }

        # PIPELINE 5: Auto-approved
        self._audit.write({
            "agent_name": agent_name,
            "model_used": model_used,
            "action_type": action_type,
            "command_or_url": command,
            "confirmation_status": "AUTO_APPROVED",
            "outcome": "SUCCESS",
            "risk_level": identified_risk,
            "path_validated": True if paths else False,
        })

        return {
            "allowed": True,
            "status": "approved",
            "message": "Action auto-approved.",
            "risk_level": identified_risk
        }

    def check_url(
        self,
        url: str,
        agent_name: str,
        model_used: str = "unknown"
    ) -> dict:
        """
        Full security check for an HTTP/HTTPS request.
        """
        res = self._network_guard.validate_url(url)
        if not res["allowed"]:
            self.report_violation(
                "NETWORK_BLOCKED",
                agent_name,
                res["reason"],
                model_used,
            )
            return {
                "allowed": False,
                "status": "blocked",
                "message": res["reason"],
                "risk_level": "blocked"
            }

        self._audit.write({
            "agent_name": agent_name,
            "model_used": model_used,
            "action_type": "HTTP_REQUEST",
            "command_or_url": url,
            "confirmation_status": "AUTO_APPROVED",
            "outcome": "SUCCESS",
            "risk_level": res["risk_level"],
            "network_validated": True,
        })
        
        return {
            "allowed": True,
            "status": "approved",
            "message": res["reason"],
            "risk_level": res["risk_level"]
        }

    def confirm(self, confirmation_key: str) -> dict:
        """
        Process a user confirmation for a pending action.
        """
        # Quick cleanup just in case
        self.cleanup_expired()

        if confirmation_key not in self._pending_confirmations:
            return {
                "status": "not_found",
                "message": "Confirmation key not found or expired.",
            }

        pending = self._pending_confirmations[confirmation_key]
        pending.received_confirmations += 1

        if pending.received_confirmations < pending.required_confirmations:
            self._audit.write({
                "agent_name": pending.agent_name,
                "action_type": pending.action_type,
                "command_or_url": pending.command,
                "confirmation_status": "CONFIRMED",
                "outcome": "PARTIAL",
            })
            
            message = "Confirmation received."
            if pending.action_type == "FILE_DELETE" and pending.received_confirmations == 1:
                path = pending.path or "file"
                message = f"First confirmation received, Sir. This is your second and final warning. The file '{path}' will be permanently deleted. Confirm again to proceed."

            return {
                "status": "confirmed_partial",
                "received_confirmations": pending.received_confirmations,
                "required_confirmations": pending.required_confirmations,
                "ready_to_execute": False,
                "message": message,
            }

        # Approaching execute
        del self._pending_confirmations[confirmation_key]
        
        self._audit.write({
            "agent_name": pending.agent_name,
            "action_type": pending.action_type,
            "command_or_url": pending.command,
            "confirmation_status": "CONFIRMED",
            "outcome": "SUCCESS",
        })

        return {
            "status": "confirmed_execute",
            "received_confirmations": pending.received_confirmations,
            "required_confirmations": pending.required_confirmations,
            "ready_to_execute": True,
            "message": "Confirmation complete. Executing action.",
            "pending_action": pending,
        }

    def cancel(self, confirmation_key: str) -> dict:
        """Cancel a pending confirmation."""
        if confirmation_key in self._pending_confirmations:
            pending = self._pending_confirmations.pop(confirmation_key)
            self._audit.write({
                "agent_name": pending.agent_name,
                "action_type": pending.action_type,
                "command_or_url": pending.command,
                "confirmation_status": "CANCELLED",
                "outcome": "FAILURE",
            })
            return {"status": "cancelled", "message": "Action cancelled."}
        return {"status": "not_found", "message": "Key not found."}

    def cleanup_expired(self) -> int:
        """Remove all expired pending confirmations and return count."""
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._pending_confirmations.items() if v.is_expired()]
        for k in expired:
            del self._pending_confirmations[k]
        return len(expired)

    def get_pending_confirmations(self) -> list[dict]:
        """Return all currently pending confirmations for status display."""
        self.cleanup_expired()
        res = []
        for v in self._pending_confirmations.values():
            res.append({
                "confirmation_key": v.confirmation_key,
                "command": v.command,
                "action_type": v.action_type,
                "agent_name": v.agent_name,
                "required_confirmations": v.required_confirmations,
                "received_confirmations": v.received_confirmations,
            })
        return res

    def get_security_status(self) -> dict:
        """Return a full security health report."""
        stats = self._audit.get_stats(24)
        chain_verify = self._audit.verify_chain()

        return {
            "path_guard_active": True,
            "network_guard_active": True,
            "audit_chain_valid": chain_verify.get("valid", False),
            "pending_confirmations": len(self._pending_confirmations),
            "violations_last_24h": stats.get("violations", 0),
            "blocked_attempts_last_24h": stats.get("blocked_attempts", 0),
            "allowed_paths": self._path_guard.get_allowed_paths(),
            "allowed_domains": self._network_guard.get_allowed_domains(),
        }


# Singleton
_security_enforcer_instance: Optional[SecurityEnforcer] = None

def get_security_enforcer() -> SecurityEnforcer:
    """Return the singleton instance of SecurityEnforcer."""
    global _security_enforcer_instance
    if _security_enforcer_instance is None:
        _security_enforcer_instance = SecurityEnforcer()
    return _security_enforcer_instance
