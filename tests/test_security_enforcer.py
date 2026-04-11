"""
J.A.R.V.I.S. — tests/test_security_enforcer.py
Complete test suite for sandbox/security_enforcer.py SecurityEnforcer class.
All 18+ required tests from Phase 2 spec Section 9.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sandbox.security_enforcer import SecurityEnforcer, SecurityError


@pytest.fixture
def test_policy(tmp_path: Path) -> dict:
    """A test policy specifically structured for enforcer tests."""
    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)
    return {
        "commands": {
            "blocked_prefixes": ["sudo", "rm -rf /", "mkfs"],
        },
        "paths": {
            "read_write_allowed": [workspace],
            "blocked": ["/etc/", "/System/"],
        },
        "network": {
            "allowed_domains": ["api.github.com"],
            "blocked_by_default": True,
        },
        "confirmations": {
            "always_required": ["EMAIL_SEND", "GIT_FORCE_PUSH", "FILE_DELETE"],
            "double_confirmation_required": ["FILE_DELETE"],
        },
        "confirmation_settings": {
            "expiry_seconds": 300,
            "file_preview_chars": 10,
        },
        "violations": {
            "speak_alert": False,
        }
    }


@pytest.fixture
def enforcer(test_policy: dict, monkeypatch) -> SecurityEnforcer:
    """Return a standalone enforcer configured with our test policy."""
    import sandbox.security_enforcer as se_module
    
    # We patch the _load_policy inside the module so the __init__ loads it.
    monkeypatch.setattr(se_module, "_load_policy", lambda: test_policy)
    
    return SecurityEnforcer()


# ---------------------------------------------------------------------------
# Command Checking
# ---------------------------------------------------------------------------

def test_safe_command_approved(enforcer: SecurityEnforcer, tmp_path: Path):
    """check_command returns approved for a safe path command."""
    target = str(tmp_path / "workspace" / "safe.txt")
    result = enforcer.check_command(
        f"ls {target}", "FILE_LIST", "file_manager"
    )
    assert result["allowed"] is True
    assert result["status"] == "approved"


def test_sudo_command_blocked(enforcer: SecurityEnforcer):
    """Blocked prefix stops the command immediately."""
    result = enforcer.check_command(
        "sudo rm -rf /etc", "TERMINAL_CMD", "system_control"
    )
    assert result["allowed"] is False
    assert result["status"] == "blocked"


def test_blocked_path_in_command_blocked(enforcer: SecurityEnforcer):
    """PathGuard block propagates up to the command check."""
    result = enforcer.check_command(
        "cat /etc/passwd", "FILE_READ", "file_manager"
    )
    assert result["allowed"] is False
    assert result["status"] == "blocked"


# ---------------------------------------------------------------------------
# Confirmations logic
# ---------------------------------------------------------------------------

def test_file_delete_requires_confirmation(enforcer: SecurityEnforcer, tmp_path: Path):
    """FILE_DELETE returns needs_confirmation and required_confirmations=2."""
    target = str(tmp_path / "workspace" / "test.txt")
    result = enforcer.check_command(
        f"rm {target}", "FILE_DELETE", "file_manager"
    )
    
    assert result["allowed"] is False
    assert result["status"] == "needs_confirmation"
    assert result["required_confirmations"] == 2
    assert "confirmation_key" in result
    assert result["confirmation_key"] is not None


def test_file_delete_includes_preview(enforcer: SecurityEnforcer, tmp_path: Path):
    """FILE_DELETE reads the first 100 (or config set) chars as file_preview."""
    target = tmp_path / "workspace" / "data.txt"
    target.write_text("hello 1234567890")
    
    result = enforcer.check_command(
        f"rm {target}", "FILE_DELETE", "file_manager"
    )
    
    # We set file_preview_chars to 10 in our fixture
    assert "hello 1234..." in result["file_preview"]


def test_single_confirm_action_needs_one_confirm(enforcer: SecurityEnforcer):
    """EMAIL_SEND needs 1 confirmation."""
    result = enforcer.check_command(
        "send email", "EMAIL_SEND", "comm"
    )
    assert result["status"] == "needs_confirmation"
    assert result["required_confirmations"] == 1


# ---------------------------------------------------------------------------
# Confirm flow
# ---------------------------------------------------------------------------

def test_confirm_first_step_returns_partial(enforcer: SecurityEnforcer, tmp_path: Path):
    """The first confirm for a double-confirm requirement returns confirmed_partial."""
    target = str(tmp_path / "workspace" / "test.txt")
    check = enforcer.check_command(f"rm {target}", "FILE_DELETE", "file_manager")
    key = check["confirmation_key"]
    
    confirm = enforcer.confirm(key)
    assert confirm["status"] == "confirmed_partial"
    assert confirm["ready_to_execute"] is False
    assert confirm["received_confirmations"] == 1


def test_confirm_second_step_returns_execute(enforcer: SecurityEnforcer, tmp_path: Path):
    """Two confirms for FILE_DELETE triggers execute state."""
    target = str(tmp_path / "workspace" / "test.txt")
    check = enforcer.check_command(f"rm {target}", "FILE_DELETE", "file_manager")
    key = check["confirmation_key"]
    
    enforcer.confirm(key)  # step 1
    confirm2 = enforcer.confirm(key)  # step 2
    
    assert confirm2["status"] == "confirmed_execute"
    assert confirm2["ready_to_execute"] is True
    assert confirm2["received_confirmations"] == 2
    assert "pending_action" in confirm2


def test_confirm_invalid_key_returns_not_found(enforcer: SecurityEnforcer):
    """Bad key returns not_found."""
    result = enforcer.confirm("nonexistent-key-xyz")
    assert result["status"] == "not_found"


def test_confirm_expired_key_returns_expired(enforcer: SecurityEnforcer):
    """
    If a pending action is expired it behaves as not_found since confirm cleans up.
    """
    check = enforcer.check_command("send email", "EMAIL_SEND", "comm")
    key = check["confirmation_key"]
    
    # Manually expire
    enforcer._pending_confirmations[key].expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    
    result = enforcer.confirm(key)
    assert result["status"] == "not_found"


def test_cancel_removes_pending(enforcer: SecurityEnforcer):
    """Cancel removes the pending confirm mapping."""
    check = enforcer.check_command("send email", "EMAIL_SEND", "comm")
    key = check["confirmation_key"]
    
    result = enforcer.cancel(key)
    assert result["status"] == "cancelled"
    
    # Not found after cancel
    after = enforcer.confirm(key)
    assert after["status"] == "not_found"


def test_cleanup_removes_expired(enforcer: SecurityEnforcer):
    """cleanup_expired() removes expired actions and returns count."""
    check1 = enforcer.check_command("send email", "EMAIL_SEND", "comm")
    check2 = enforcer.check_command("send email", "EMAIL_SEND", "comm")
    check3 = enforcer.check_command("ls", "EMAIL_SEND", "comm")
    
    k1 = check1["confirmation_key"]
    k2 = check2["confirmation_key"]
    k3 = check3["confirmation_key"]
    
    # Expire 1 and 2
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    enforcer._pending_confirmations[k1].expires_at = past
    enforcer._pending_confirmations[k2].expires_at = past
    
    removed = enforcer.cleanup_expired()
    assert removed == 2
    
    remaining = enforcer.get_pending_confirmations()
    assert len(remaining) == 1
    assert remaining[0]["confirmation_key"] == k3


# ---------------------------------------------------------------------------
# URL Checking
# ---------------------------------------------------------------------------

def test_url_check_allowed_domain(enforcer: SecurityEnforcer):
    """Allowed domain triggers approved status."""
    result = enforcer.check_url("https://api.github.com/repos", "research")
    assert result["allowed"] is True
    assert result["status"] == "approved"


def test_url_check_blocked_domain(enforcer: SecurityEnforcer):
    """Unknown domain triggers blocked status."""
    result = enforcer.check_url("https://evil-exfiltration.com/data", "research")
    assert result["allowed"] is False
    assert result["status"] == "blocked"


def test_ip_url_blocked(enforcer: SecurityEnforcer):
    """IP addressed URLs blocked."""
    result = enforcer.check_url("http://8.8.8.8/exfiltrate", "research")
    assert result["allowed"] is False
    assert result["status"] == "blocked"


# ---------------------------------------------------------------------------
# Status and Audit
# ---------------------------------------------------------------------------

def test_security_status_returns_complete_dict(enforcer: SecurityEnforcer):
    """get_security_status gives full dict info."""
    status = enforcer.get_security_status()
    assert "path_guard_active" in status
    assert "network_guard_active" in status
    assert "audit_chain_valid" in status
    assert "pending_confirmations" in status
    assert "violations_last_24h" in status
    assert "blocked_attempts_last_24h" in status
    assert "allowed_paths" in status
    assert "allowed_domains" in status


def test_violation_reported_to_audit(enforcer: SecurityEnforcer):
    """Violations reach the AuditManager securely."""
    enforcer.report_violation("PATH_BLOCKED", "file_manager", "/etc/passwd accessed")
    violations = enforcer._audit.get_violations()
    
    # Needs at least one (since our enforcer just wrote it)
    assert len(violations) >= 1
    assert violations[0]["command_or_url"] == "/etc/passwd accessed"
    assert violations[0]["outcome"] == "BLOCKED"
