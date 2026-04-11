"""
J.A.R.V.I.S. — sandbox/path_guard.py
Path restriction enforcement for all file system operations.
Consults jarvis_security.yaml for allowed and blocked paths.

Security principle: DENY BY DEFAULT, ALLOW BY EXCEPTION.
The blocked list is checked FIRST and takes precedence over all allowed lists.
A path not in any allowed list is denied.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_SECURITY_POLICY_PATH = Path(__file__).parent / "jarvis_security.yaml"

# Sensitive file patterns — extra warnings even in allowed directories
_SENSITIVE_EXTENSIONS = {".env", ".key", ".pem", ".p12", ".pfx", ".cert", ".crt", ".keystore"}
_SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production",
    "id_rsa", "id_ed25519", "credentials.json",
    "jarvis_vertex_key.json",
}

# Path traversal patterns (raw and URL-encoded)
_TRAVERSAL_PATTERNS = [
    r"\.\.",                # basic ..
    r"%2e%2e",             # URL-encoded ..
    r"%2f",                # URL-encoded /
    r"\.\.%2f",            # ../  URL-encoded slash
    r"%2e%2e%2f",          # URL-encoded ../
    r"\.\.\\",             # Windows traversal
    r"\x00",               # null byte
    r"%00",                # URL-encoded null byte
    r"~.*\.\.",            # tilde + traversal
]


def _load_policy() -> dict:
    """Load the JARVIS security policy from jarvis_security.yaml."""
    try:
        with _SECURITY_POLICY_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.warning("Security policy not found at %s.", _SECURITY_POLICY_PATH)
        return {}
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load security policy: %s", exc)
        return {}


class PathGuard:
    """
    File system path restriction enforcement for J.A.R.V.I.S.

    Maintains three lists loaded from jarvis_security.yaml:
      - read_write_allowed: paths where agents may read, write, and delete
      - read_only_allowed:  paths where agents may only read/list
      - blocked:            paths that are NEVER accessible (takes precedence)

    Rule: blocked paths are checked FIRST. A path not in any list is DENIED.
    """

    def __init__(self, policy: dict) -> None:
        """
        Load path rules from the policy dict.

        Args:
            policy: The full parsed jarvis_security.yaml dict.
        """
        paths_section = policy.get("paths", {})

        # Expand ~ and convert to absolute strings
        self._read_write: list[str] = [
            os.path.expanduser(p)
            for p in paths_section.get("read_write_allowed", [])
        ]
        self._read_only: list[str] = [
            os.path.expanduser(p)
            for p in paths_section.get("read_only", [])
        ]
        self._blocked: list[str] = [
            os.path.expanduser(p)
            for p in paths_section.get("blocked", [])
        ]

        # Load sensitive patterns from policy if present
        sensitive = policy.get("sensitive_patterns", {})
        self._sensitive_extensions: set[str] = set(
            sensitive.get("file_extensions", list(_SENSITIVE_EXTENSIONS))
        )
        self._sensitive_names: set[str] = set(
            sensitive.get("file_names", list(_SENSITIVE_NAMES))
        )

        logger.debug(
            "PathGuard initialised — rw=%d, ro=%d, blocked=%d",
            len(self._read_write), len(self._read_only), len(self._blocked),
        )

    def validate(self, path: str, operation: str = "read") -> dict:
        """
        Validate whether a path is accessible for a given operation.

        Args:
            path: The file or directory path to check. May be absolute or relative.
            operation: One of "read", "write", "delete", "list".

        Returns:
            dict with keys:
              allowed (bool): True if the operation is permitted.
              reason (str): Human-readable explanation.
              resolved_path (str): The real absolute path after resolving symlinks.
              risk_level (str): "safe", "caution", or "blocked".
        """
        expanded = os.path.expanduser(str(path))

        # Detect traversal early — before resolution
        if self.is_path_traversal_attempt(path):
            try:
                resolved_path = str(Path(expanded).resolve())
            except Exception:
                resolved_path = expanded
            return {
                "allowed": False,
                "reason": f"Path traversal attempt detected in: {path}",
                "resolved_path": resolved_path,
                "risk_level": "blocked",
            }

        # Resolve to real absolute path (prevents symlink/traversal bypasses)
        try:
            resolved = Path(expanded).resolve()
            resolved_path = str(resolved)
        except Exception as exc:
            return {
                "allowed": False,
                "reason": f"Cannot resolve path '{path}': {exc}",
                "resolved_path": expanded,
                "risk_level": "blocked",
            }

        # Check symlink attack: symlink pointing into a blocked directory
        if os.path.islink(expanded):
            for blocked in self._blocked:
                blocked_resolved = os.path.expanduser(blocked)
                if resolved_path.startswith(blocked_resolved):
                    return {
                        "allowed": False,
                        "reason": (
                            f"Symlink '{path}' resolves to blocked directory '{blocked}'. "
                            "Symlink attacks are not permitted."
                        ),
                        "resolved_path": resolved_path,
                        "risk_level": "blocked",
                    }

        # LAYER 1: Check blocked list FIRST — takes absolute precedence
        for blocked in self._blocked:
            blocked_abs = os.path.abspath(os.path.expanduser(blocked))
            if resolved_path.startswith(blocked_abs) or resolved_path == blocked_abs:
                return {
                    "allowed": False,
                    "reason": f"Path '{path}' is in a blocked directory: {blocked}",
                    "resolved_path": resolved_path,
                    "risk_level": "blocked",
                }

        # LAYER 2: For write/delete — only read_write_allowed paths are permitted
        if operation in ("write", "delete"):
            for allowed in self._read_write:
                allowed_abs = os.path.abspath(allowed)
                if resolved_path.startswith(allowed_abs):
                    risk = "caution" if self.is_sensitive_path(path) else "safe"
                    return {
                        "allowed": True,
                        "reason": f"Path is in read-write allowed directory: {allowed}",
                        "resolved_path": resolved_path,
                        "risk_level": risk,
                    }
            return {
                "allowed": False,
                "reason": (
                    f"Path '{path}' is not in a read-write allowed directory. "
                    f"Operation '{operation}' requires explicit write permission."
                ),
                "resolved_path": resolved_path,
                "risk_level": "blocked",
            }

        # LAYER 3: For read/list — both read_write and read_only are permitted
        all_allowed = self._read_write + self._read_only
        for allowed in all_allowed:
            allowed_abs = os.path.abspath(os.path.expanduser(allowed))
            if resolved_path.startswith(allowed_abs):
                risk = "caution" if self.is_sensitive_path(path) else "safe"
                return {
                    "allowed": True,
                    "reason": f"Path is in allowed directory: {allowed}",
                    "resolved_path": resolved_path,
                    "risk_level": risk,
                }

        # Default: deny (not in any allowed list)
        return {
            "allowed": False,
            "reason": (
                f"Path '{path}' is not in any allowed directory. "
                "JARVIS operates on an explicit allow-list. "
                "Add the path to jarvis_security.yaml to permit access."
            ),
            "resolved_path": resolved_path,
            "risk_level": "blocked",
        }

    def is_path_traversal_attempt(self, path: str) -> bool:
        """
        Detect if a path contains traversal sequences.

        Args:
            path: Raw path string from agent.

        Returns:
            True if path traversal is detected, False otherwise.
        """
        path_lower = path.lower()
        for pattern in _TRAVERSAL_PATTERNS:
            if re.search(pattern, path_lower, re.IGNORECASE):
                logger.warning("Path traversal pattern detected in: %s", path)
                return True
        return False

    def get_allowed_paths(self) -> dict:
        """
        Return the current allowed path configuration for display.

        Returns:
            dict with read_write, read_only, and blocked lists.
        """
        return {
            "read_write": self._read_write,
            "read_only": self._read_only,
            "blocked": self._blocked,
        }

    def is_sensitive_path(self, path: str) -> bool:
        """
        Check if a path is in a sensitive category even if technically allowed.
        Used to trigger extra warnings (caution risk_level) in the audit log.

        Sensitive: .env files, .key/.pem/.p12 certs, credential files,
        any file ending in known sensitive extensions.

        Args:
            path: Path string to check.

        Returns:
            True if the path is considered sensitive, False otherwise.
        """
        p = Path(os.path.expanduser(str(path)))
        name = p.name.lower()
        suffix = p.suffix.lower()

        # Check extension
        if suffix in self._sensitive_extensions:
            return True

        # Check name (includes dotfiles like .env)
        if name in self._sensitive_names:
            return True

        # Check wildcard *.secret pattern
        if name.endswith(".secret"):
            return True

        return False


def check_path(path: str, operation: str = "read", policy: Optional[dict] = None) -> dict:
    """
    Convenience function — create a PathGuard and validate in one call.

    Args:
        path: File or directory path to check.
        operation: One of "read", "write", "delete", "list".
        policy: Policy dict. If None, loads from jarvis_security.yaml.

    Returns:
        PathGuard.validate() result dict.
    """
    if policy is None:
        policy = _load_policy()
    guard = PathGuard(policy)
    return guard.validate(path, operation)
