"""
J.A.R.V.I.S. — tests/test_executor.py
Sandbox executor tests — covering GAP 4 double-confirmation fix and security policy.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0 (Gap Fix)
"""

import pytest
import sandbox.executor as executor_module
from sandbox.executor import Executor, SecurityError


@pytest.fixture
def executor():
    """Return a fresh Executor instance for each test."""
    return Executor()


@pytest.fixture
def executor_no_path_block(monkeypatch):
    """
    Executor with path blocking removed from the policy.
    Used for confirmation flow tests where we need absolute paths
    but don’t want the broad '/' blocked-path rule to interfere.
    The '/' blocking is already verified in separate dedicated tests.
    """
    def mock_policy():
        return {
            "paths": {
                "blocked": ["/etc/", "/System/", "/Library/Keychains/", "~/.ssh/"],
            },
            "commands": {
                "blocked_prefixes": ["sudo", "su ", "chmod 777", "rm -rf /"],
            },
            "confirmations": {
                "always_required": ["FILE_DELETE", "EMAIL_SEND", "PURCHASE"],
                "double_confirmation_required": ["FILE_DELETE", "PURCHASE"],
            },
        }
    monkeypatch.setattr(executor_module, "_load_policy", mock_policy)
    return Executor()


# ---------------------------------------------------------------------------
# Blocked command prefixes
# ---------------------------------------------------------------------------

def test_sudo_command_raises_security_error(executor):
    """sudo commands must be blocked by security policy."""
    with pytest.raises(SecurityError):
        executor.execute("sudo rm -rf /tmp/test", "SYSTEM_COMMAND", "system_control")


def test_rm_rf_root_raises_security_error(executor):
    """rm -rf / must be blocked."""
    with pytest.raises(SecurityError):
        executor.execute("rm -rf /", "FILE_DELETE", "file_manager")


# ---------------------------------------------------------------------------
# Single confirmation flow
# ---------------------------------------------------------------------------

def test_file_delete_requires_confirmation(executor_no_path_block):
    """FILE_DELETE must return needs_confirmation on first call without confirmed=True."""
    result = executor_no_path_block.execute("rm /Users/hparichha/Documents/Jarvis/test_file.txt", "FILE_DELETE", "file_manager")
    assert result["status"] == "needs_confirmation"
    assert "confirmation_key" in result
    assert result["confirmations_received"] == 0
    assert result["required_confirmations"] >= 1


def test_email_send_requires_single_confirmation(executor):
    """EMAIL_SEND requires confirmation but not double."""
    result = executor.execute("send_email --to test@example.com", "EMAIL_SEND", "communication")
    assert result["status"] == "needs_confirmation"
    assert "confirmation_key" in result
    # EMAIL_SEND is always_required but NOT double_required
    assert result["required_confirmations"] == 1


# ---------------------------------------------------------------------------
# GAP 4 FIX: Double confirmation — the core of the fix
# ---------------------------------------------------------------------------

def test_file_delete_double_confirmation_first_step(executor_no_path_block):
    """
    GAP 4 FIX: FILE_DELETE double confirmation — first confirm should NOT execute,
    should return needs_confirmation with confirmations_received=1.
    """
    # Step 1: Initial call — triggers confirmation request
    result = executor_no_path_block.execute("rm /Users/hparichha/Documents/Jarvis/important_file.txt", "FILE_DELETE", "file_manager")
    assert result["status"] == "needs_confirmation"
    key = result["confirmation_key"]
    assert result["required_confirmations"] == 2  # double required
    assert result["confirmations_received"] == 0

    # Step 2: First confirm — should NOT execute yet
    result2 = executor_no_path_block.confirm(key)
    assert result2["status"] == "needs_confirmation"  # still needs 1 more
    assert result2["confirmations_received"] == 1
    assert result2["required_confirmations"] == 2


def test_confirmation_key_returned_in_response(executor_no_path_block):
    """The confirmation_key must be present in the needs_confirmation response."""
    result = executor_no_path_block.execute("rm /Users/hparichha/Documents/Jarvis/old_project", "FILE_DELETE", "file_manager")
    assert result["status"] == "needs_confirmation"
    assert "confirmation_key" in result
    assert len(result["confirmation_key"]) > 0


def test_confirm_with_invalid_key_returns_failed(executor):
    """Calling confirm() with a non-existent key should return a failed status."""
    result = executor.confirm("nonexistent_key_12345")
    assert result["status"] == "failed"
    assert "error" in result


def test_single_confirmation_action_executes_after_one_confirm(executor):
    """EMAIL_SEND (single confirm only) should be ready to execute after one confirm call."""
    # Step 1: request
    result = executor.execute("send_email --to test@example.com", "EMAIL_SEND", "communication")
    assert result["status"] == "needs_confirmation"
    assert result["required_confirmations"] == 1
    key = result["confirmation_key"]

    # Step 2: First confirm should attempt execution (may fail, but not needs_confirmation)
    # We don't care if it succeeds — just that it's NOT "needs_confirmation" anymore
    result2 = executor.confirm(key)
    # After 1 confirm for a single-required action, it should execute (success or failed)
    assert result2["status"] in ("success", "failed", "rejected")


# ---------------------------------------------------------------------------
# Cancel flow
# ---------------------------------------------------------------------------

def test_cancel_pending_action(executor_no_path_block):
    """cancel() should remove the pending action and return 'cancelled'."""
    result = executor_no_path_block.execute("rm /Users/hparichha/Documents/Jarvis/test.txt", "FILE_DELETE", "file_manager")
    assert result["status"] == "needs_confirmation"
    key = result["confirmation_key"]

    cancel_result = executor_no_path_block.cancel(key)
    assert cancel_result["status"] == "cancelled"

    # Subsequent confirm should fail — action is gone
    confirm_after_cancel = executor_no_path_block.confirm(key)
    assert confirm_after_cancel["status"] == "failed"


def test_cancel_nonexistent_key_returns_not_found(executor):
    """cancel() with a bad key should return not_found."""
    result = executor.cancel("bad_key_xyz")
    assert result["status"] == "not_found"


# ---------------------------------------------------------------------------
# Auto-approved actions (no confirmation needed)
# ---------------------------------------------------------------------------

def test_simple_command_auto_approved(executor):
    """Commands with action_type not in always_required should execute immediately."""
    result = executor.execute("echo hello_jarvis", "CHAT", "receptionist")
    # Should execute immediately — success or failed based on shell
    assert result["status"] in ("success", "failed")
    assert "output" in result
