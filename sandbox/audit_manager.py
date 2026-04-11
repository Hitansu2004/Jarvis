"""
J.A.R.V.I.S. — sandbox/audit_manager.py
Tamper-evident audit log manager with SHA-256 chain integrity.
Every audit entry is hashed. Each hash includes the previous entry's hash,
creating a chain — any tampering breaks the chain and is detectable.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path(__file__).parent / "audit.log"
_DOTENV_PATH = Path(__file__).parent.parent / ".env"


class AuditManager:
    """
    Tamper-evident audit log manager.
    Maintains a local JSON-lines log file where each entry is cryptographically
    linked to the previous one via SHA-256 hashes.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        """
        Initialise the audit manager.

        Args:
            log_path: Path to the audit log file. Defaults to sandbox/audit.log.
        """
        self.log_path = log_path or _DEFAULT_LOG_PATH
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        # Load redaction patterns
        self._sensitive_patterns = self._load_sensitive_patterns()

        # Initialise chain state
        self.seq = 1
        self.last_hash = "GENESIS"
        self._init_chain()

    def _init_chain(self) -> None:
        """Read the last entry from the log file to resume the hash chain and sequence."""
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return  # Empty log, stay at seq 1 and GENESIS

        last_line = ""
        try:
            # Read the last line efficiently (for large logs, doing readlines is bad, but
            # since this is a simple implementation, reading lines and taking the last is ok.
            # We can optimise if needed.)
            with self.log_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        last_line = line

            if last_line:
                data = json.loads(last_line)
                self.seq = data.get("seq", 0) + 1
                self.last_hash = data.get("entry_hash", "GENESIS")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to initialise audit chain: %s", exc)
            self.seq = 1
            self.last_hash = "GENESIS"

    def _load_sensitive_patterns(self) -> list[tuple[re.Pattern, str]]:
        """
        Load sensitive values from .env to redact them.
        Returns a list of tuples: (compiled regex pattern, replacement string).
        """
        patterns = []

        # Known generic API key patterns
        patterns.extend([
            (re.compile(r"sk-ant-[a-zA-Z0-9-_]+"), "[REDACTED:ANTHROPIC_KEY]"),
            (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[REDACTED:OPENAI_KEY]"),
            (re.compile(r"AIza[a-zA-Z0-9_-]+"), "[REDACTED:GOOGLE_API_KEY]"),
            (re.compile(r"ya29\.[a-zA-Z0-9_-]+"), "[REDACTED:GOOGLE_OAUTH]"),
            (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "[REDACTED:GITHUB_PAT]"),
        ])

        # Load from .env if it exists
        if _DOTENV_PATH.exists():
            try:
                with _DOTENV_PATH.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("'\"")
                            
                            # If key ends with sensitive suffixes, mask its value
                            if any(key.endswith(suffix) for suffix in ["_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIALS"]) and val:
                                escaped_val = re.escape(val)
                                patterns.append(
                                    (re.compile(escaped_val), f"[REDACTED:{key}]")
                                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read .env for redaction: %s", exc)

        return patterns

    def _redact(self, text: str) -> str:
        """Redact sensitive values like API keys from the text."""
        if not text:
            return text
            
        redacted = text
        for pattern, replacement in self._sensitive_patterns:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def _compute_hash(self, entry: dict) -> str:
        """Compute the deterministic SHA-256 hash of an entry dict."""
        # Create a copy without the entry_hash field itself
        hash_dict = {k: v for k, v in entry.items() if k != "entry_hash"}
        # Convert to deterministic JSON string (sorted keys)
        canon_json = json.dumps(hash_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon_json.encode("utf-8")).hexdigest()

    def write(self, entry: dict) -> str:
        """
        Write a single audit entry with hash chaining.

        Args:
            entry: Dict with audit fields. Required: agent_name, action_type, outcome.

        Returns:
            The entry_hash string for this entry.
        """
        with self._lock:
            # 1. Add seq, timestamp, prev_hash
            full_entry = {
                "seq": self.seq,
                "timestamp": entry.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                "agent_name": entry.get("agent_name", "unknown"),
                "model_used": entry.get("model_used", "unknown"),
                "action_type": entry.get("action_type", "UNKNOWN"),
                "command_or_url": entry.get("command_or_url", ""),
                "confirmation_status": entry.get("confirmation_status", "AUTO_APPROVED"),
                "outcome": entry.get("outcome", "SUCCESS"),
                "error_message": entry.get("error_message"),
                "risk_level": entry.get("risk_level", "safe"),
                "path_validated": entry.get("path_validated", False),
                "network_validated": entry.get("network_validated", False),
                "prev_hash": self.last_hash,
            }

            # 2. REDACT sensitive values from command_or_url and error_message
            if isinstance(full_entry["command_or_url"], str):
                full_entry["command_or_url"] = self._redact(full_entry["command_or_url"])
            if isinstance(full_entry["error_message"], str):
                full_entry["error_message"] = self._redact(full_entry["error_message"])

            # 3. Compute entry_hash
            entry_hash = self._compute_hash(full_entry)
            full_entry["entry_hash"] = entry_hash

            # 4. Write JSON line
            try:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(full_entry) + "\n")
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to write audit entry: %s", exc)
                # Note: If writing fails, we don't advance the sequence or hash
                raise

            # 5. Update state
            self.seq += 1
            self.last_hash = entry_hash

            return entry_hash

    def verify_chain(self) -> dict:
        """
        Verify the integrity of the entire audit log chain.

        Returns:
            dict summarizing the chain validity.
        """
        result = {
            "valid": True,
            "total_entries": 0,
            "first_broken_at": None,
            "error": None,
        }

        if not self.log_path.exists():
            return result

        expected_prev_hash = "GENESIS"
        
        with self._lock:
            try:
                with self.log_path.open("r", encoding="utf-8") as fh:
                    for line_num, line in enumerate(fh, start=1):
                        line = line.strip()
                        if not line:
                            continue
                            
                        result["total_entries"] += 1
                        
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            result["valid"] = False
                            result["first_broken_at"] = line_num
                            result["error"] = f"JSON parsing failed at line {line_num}"
                            return result

                        stored_hash = entry.get("entry_hash")
                        prev_hash = entry.get("prev_hash")
                        
                        # Verify link to previous
                        if prev_hash != expected_prev_hash:
                            result["valid"] = False
                            result["first_broken_at"] = entry.get("seq", line_num)
                            result["error"] = f"Broken chain at line {line_num}: prev_hash mismatch"
                            return result
                            
                        # Verify content integrity
                        computed_hash = self._compute_hash(entry)
                        if computed_hash != stored_hash:
                            result["valid"] = False
                            result["first_broken_at"] = entry.get("seq", line_num)
                            result["error"] = f"Tampering detected at line {line_num}: content hash mismatch"
                            return result
                            
                        expected_prev_hash = stored_hash
                        
            except Exception as exc:  # noqa: BLE001
                result["valid"] = False
                result["error"] = f"Error reading log file: {exc}"

        return result

    def get_recent(self, limit: int = 50, action_type: Optional[str] = None) -> list[dict]:
        """
        Return the most recent audit entries, optionally filtered by action_type.
        """
        entries = []
        if not self.log_path.exists():
            return entries

        with self._lock:
            try:
                with self.log_path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if action_type is None or entry.get("action_type") == action_type:
                                entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Error reading recent entries: %s", exc)

        # Optimization logic: reading the whole file in memory and then slicing.
        # Acceptable for Phase 2 logs, can use something like `tail` logic eventually.
        return list(reversed(entries))[:limit]

    def get_violations(self, since_hours: int = 24) -> list[dict]:
        """
        Return all SECURITY_VIOLATION entries from the last N hours.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        cutoff_iso = cutoff.isoformat()
        
        violations = []
        if not self.log_path.exists():
            return violations

        with self._lock:
            try:
                with self.log_path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if entry.get("action_type") == "SECURITY_VIOLATION":
                                ts = entry.get("timestamp", "")
                                if ts >= cutoff_iso:
                                    violations.append(entry)
                                elif ts < cutoff_iso:
                                    pass # Log could be ordered, but time strings are sortable
                        except json.JSONDecodeError:
                            continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Error reading violations: %s", exc)
                
        return list(reversed(violations))

    def get_stats(self, since_hours: int = 24) -> dict:
        """
        Return audit statistics for the last N hours.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        cutoff_iso = cutoff.isoformat()
        
        stats = {
            "total_actions": 0,
            "by_action_type": {},
            "by_outcome": {},
            "violations": 0,
            "blocked_attempts": 0,
            "agents_active": set(),
        }
        
        if not self.log_path.exists():
            # Convert set to list before returning
            stats["agents_active"] = list(stats["agents_active"])
            return stats

        with self._lock:
            try:
                with self.log_path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            ts = entry.get("timestamp", "")
                            
                            # Only consider recent entries
                            if ts < cutoff_iso:
                                continue
                                
                            stats["total_actions"] += 1
                            
                            atype = entry.get("action_type", "UNKNOWN")
                            stats["by_action_type"][atype] = stats["by_action_type"].get(atype, 0) + 1
                            
                            outcome = entry.get("outcome", "UNKNOWN")
                            stats["by_outcome"][outcome] = stats["by_outcome"].get(outcome, 0) + 1
                            
                            if atype == "SECURITY_VIOLATION":
                                stats["violations"] += 1
                                
                            if outcome == "BLOCKED":
                                stats["blocked_attempts"] += 1
                                
                            agent = entry.get("agent_name")
                            if agent and agent != "unknown":
                                stats["agents_active"].add(agent)
                                
                        except json.JSONDecodeError:
                            continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Error generating stats: %s", exc)

        stats["agents_active"] = list(stats["agents_active"])
        return stats


# Global singleton instance
_audit_manager_instance: Optional[AuditManager] = None

def get_audit_manager() -> AuditManager:
    """Return the singleton instance of AuditManager."""
    global _audit_manager_instance
    if _audit_manager_instance is None:
        _audit_manager_instance = AuditManager()
    return _audit_manager_instance
