"""
J.A.R.V.I.S. — tests/test_path_guard.py
Complete test suite for sandbox/path_guard.py PathGuard class.
All 14+ required tests from Phase 2 spec Section 9.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from sandbox.path_guard import PathGuard, check_path


@pytest.fixture
def policy(tmp_path: Path) -> dict:
    """
    Build a test policy dict using tmp_path so tests are filesystem-independent.
    """
    workspace = str(tmp_path / "workspace")
    desktop = str(tmp_path / "desktop")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(desktop, exist_ok=True)
    return {
        "paths": {
            "read_write_allowed": [workspace],
            "read_only": [desktop],
            "blocked": ["/etc/", "/System/", "~/.ssh/"],
        },
        "sensitive_patterns": {
            "file_extensions": [".env", ".key", ".pem", ".p12", ".pfx"],
            "file_names": [".env", "id_rsa", "credentials.json"],
        },
    }


@pytest.fixture
def guard(policy: dict) -> PathGuard:
    """Return a PathGuard instance with the test policy."""
    return PathGuard(policy)


# ---------------------------------------------------------------------------
# Read operations — allowed paths
# ---------------------------------------------------------------------------

def test_allowed_path_read_returns_allowed(guard: PathGuard, tmp_path: Path):
    """A path inside the read_write workspace/ with operation='read' returns allowed=True."""
    target = str(tmp_path / "workspace" / "test.py")
    # Create the file so resolve() works
    Path(target).touch()
    result = guard.validate(target, "read")
    assert result["allowed"] is True
    assert result["risk_level"] in ("safe", "caution")


def test_allowed_path_write_returns_allowed(guard: PathGuard, tmp_path: Path):
    """A path inside workspace/ with operation='write' returns allowed=True."""
    target = str(tmp_path / "workspace" / "output.txt")
    Path(target).touch()
    result = guard.validate(target, "write")
    assert result["allowed"] is True


def test_read_only_path_read_returns_allowed(guard: PathGuard, tmp_path: Path):
    """A path inside desktop/ with operation='read' returns allowed=True."""
    target = str(tmp_path / "desktop" / "notes.txt")
    Path(target).touch()
    result = guard.validate(target, "read")
    assert result["allowed"] is True


def test_read_only_path_write_returns_blocked(guard: PathGuard, tmp_path: Path):
    """
    A path inside desktop/ (read_only) with operation='write' returns allowed=False.
    The reason should mention that write permission is not granted.
    """
    target = str(tmp_path / "desktop" / "notes.txt")
    Path(target).touch()
    result = guard.validate(target, "write")
    assert result["allowed"] is False
    # Reason should indicate the restriction
    assert "write" in result["reason"].lower() or "read" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Blocked paths
# ---------------------------------------------------------------------------

def test_blocked_path_returns_blocked(guard: PathGuard):
    """/etc/passwd with any operation returns allowed=False with risk_level='blocked'."""
    result = guard.validate("/etc/passwd", "read")
    assert result["allowed"] is False
    assert result["risk_level"] == "blocked"


def test_blocked_path_system_returns_blocked(guard: PathGuard):
    """/System/ path always blocked."""
    result = guard.validate("/System/Library/Extensions", "read")
    assert result["allowed"] is False
    assert result["risk_level"] == "blocked"


# ---------------------------------------------------------------------------
# Path traversal detection
# ---------------------------------------------------------------------------

def test_path_traversal_detected(guard: PathGuard, tmp_path: Path):
    """'workspace/../../etc/passwd' is detected as a traversal attempt."""
    target = str(tmp_path / "workspace" / ".." / ".." / "etc" / "passwd")
    assert guard.is_path_traversal_attempt(target) is True


def test_path_traversal_blocked_in_validate(guard: PathGuard, tmp_path: Path):
    """validate('workspace/../../etc/passwd', 'read') returns allowed=False."""
    target = str(tmp_path / "workspace") + "/../../etc/passwd"
    result = guard.validate(target, "read")
    assert result["allowed"] is False


def test_url_encoded_traversal_detected(guard: PathGuard, tmp_path: Path):
    """URL-encoded traversal '%2e%2e' is detected."""
    target = str(tmp_path / "workspace") + "/%2e%2e%2fetc%2fpasswd"
    assert guard.is_path_traversal_attempt(target) is True


def test_null_byte_traversal_detected(guard: PathGuard, tmp_path: Path):
    """Null byte in path is detected as traversal."""
    target = str(tmp_path / "workspace" / "file\x00.txt")
    assert guard.is_path_traversal_attempt(target) is True


# ---------------------------------------------------------------------------
# Deny by default
# ---------------------------------------------------------------------------

def test_unknown_path_blocked_by_default(guard: PathGuard, tmp_path: Path):
    """A path not in any list returns allowed=False (deny by default)."""
    # Use a path completely outside workspace and desktop
    target = str(tmp_path / "unknown_dir" / "file.txt")
    result = guard.validate(target, "read")
    assert result["allowed"] is False
    assert result["risk_level"] == "blocked"


# ---------------------------------------------------------------------------
# resolved_path always returned
# ---------------------------------------------------------------------------

def test_resolved_path_returned(guard: PathGuard, tmp_path: Path):
    """validate() always returns a 'resolved_path' key in the result dict."""
    target = str(tmp_path / "workspace" / "file.py")
    Path(target).touch()
    result = guard.validate(target, "read")
    assert "resolved_path" in result
    assert len(result["resolved_path"]) > 0


# ---------------------------------------------------------------------------
# Sensitive file detection
# ---------------------------------------------------------------------------

def test_sensitive_file_flagged(guard: PathGuard, tmp_path: Path):
    """is_sensitive_path() returns True for .env files, False for normal code."""
    env_path = str(tmp_path / "workspace" / ".env")
    code_path = str(tmp_path / "workspace" / "mycode.py")
    assert guard.is_sensitive_path(env_path) is True
    assert guard.is_sensitive_path(code_path) is False


def test_sensitive_pem_flagged(guard: PathGuard, tmp_path: Path):
    """is_sensitive_path() returns True for .pem certificate files."""
    pem_path = str(tmp_path / "workspace" / "server.pem")
    assert guard.is_sensitive_path(pem_path) is True


def test_sensitive_id_rsa_flagged(guard: PathGuard, tmp_path: Path):
    """is_sensitive_path() returns True for id_rsa (SSH key)."""
    rsa_path = str(tmp_path / "workspace" / "id_rsa")
    assert guard.is_sensitive_path(rsa_path) is True


# ---------------------------------------------------------------------------
# get_allowed_paths
# ---------------------------------------------------------------------------

def test_get_allowed_paths_returns_correct_structure(guard: PathGuard):
    """get_allowed_paths() returns dict with read_write, read_only, blocked keys."""
    result = guard.get_allowed_paths()
    assert "read_write" in result
    assert "read_only" in result
    assert "blocked" in result
    assert isinstance(result["read_write"], list)
    assert isinstance(result["read_only"], list)
    assert isinstance(result["blocked"], list)


# ---------------------------------------------------------------------------
# Blocked takes precedence over allowed
# ---------------------------------------------------------------------------

def test_blocked_takes_precedence_over_allowed():
    """If a path is in both allowed and blocked, blocked wins."""
    policy_overlap = {
        "paths": {
            "read_write_allowed": ["/etc/"],   # also in blocked
            "read_only": [],
            "blocked": ["/etc/"],
        },
    }
    guard = PathGuard(policy_overlap)
    result = guard.validate("/etc/passwd", "read")
    assert result["allowed"] is False
    assert result["risk_level"] == "blocked"


# ---------------------------------------------------------------------------
# Delete operation on read_only path
# ---------------------------------------------------------------------------

def test_delete_operation_blocked_on_read_only(guard: PathGuard, tmp_path: Path):
    """A path in read_only with operation='delete' returns allowed=False."""
    target = str(tmp_path / "desktop" / "important.txt")
    Path(target).touch()
    result = guard.validate(target, "delete")
    assert result["allowed"] is False


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def test_check_path_convenience_function(tmp_path: Path, policy: dict):
    """check_path() convenience function works with explicit policy."""
    target = str(tmp_path / "workspace" / "data.json")
    Path(target).touch()
    result = check_path(target, "read", policy)
    assert result["allowed"] is True
