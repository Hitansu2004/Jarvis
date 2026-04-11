"""
J.A.R.V.I.S. — tests/test_audit_manager.py
Complete test suite for sandbox/audit_manager.py AuditManager class.
All 14+ required tests from Phase 2 spec Section 9.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from sandbox.audit_manager import AuditManager


@pytest.fixture
def audit(tmp_path: Path) -> AuditManager:
    """Return a fresh AuditManager instance with a temp log file."""
    log_file = tmp_path / "audit.log"
    # Also write a dummy .env in tmp_path and patch _DOTENV_PATH later if needed,
    # but the class reads from sandbox directory. We can patch it.
    return AuditManager(log_path=log_file)


@pytest.fixture
def manager_with_env(tmp_path: Path, monkeypatch) -> AuditManager:
    """Return an AuditManager with a mock .env file to test redaction."""
    env_file = tmp_path / ".env"
    env_file.write_text("MY_SECRET_KEY=super_secret_12345\nAWS_TOKEN='aws_xyz'\n")
    
    import sandbox.audit_manager as am_module
    monkeypatch.setattr(am_module, "_DOTENV_PATH", env_file)
    
    log_file = tmp_path / "audit.log"
    return AuditManager(log_path=log_file)


# ---------------------------------------------------------------------------
# Core writing and chain mechanics
# ---------------------------------------------------------------------------

def test_write_creates_entry_with_required_fields(audit: AuditManager):
    """Write an entry and verify all required fields are present."""
    entry_hash = audit.write({
        "agent_name": "test_agent",
        "action_type": "FILE_READ",
        "outcome": "SUCCESS",
    })
    
    with audit.log_path.open("r") as f:
        data = json.loads(f.read().strip())
        
    assert data["seq"] == 1
    assert "timestamp" in data
    assert data["agent_name"] == "test_agent"
    assert data["action_type"] == "FILE_READ"
    assert data["outcome"] == "SUCCESS"
    assert data["entry_hash"] == entry_hash
    assert data["prev_hash"] == "GENESIS"


def test_seq_increments(audit: AuditManager):
    """Write 3 entries and verify seq values."""
    audit.write({"agent_name": "a", "action_type": "CHAT"})
    audit.write({"agent_name": "b", "action_type": "CHAT"})
    audit.write({"agent_name": "c", "action_type": "CHAT"})
    
    lines = audit.log_path.read_text().strip().split("\n")
    assert len(lines) == 3
    
    data1 = json.loads(lines[0])
    data2 = json.loads(lines[1])
    data3 = json.loads(lines[2])
    
    assert data1["seq"] == 1
    assert data2["seq"] == 2
    assert data3["seq"] == 3


def test_first_entry_has_genesis_prev_hash(audit: AuditManager):
    """First entry written to empty log has prev_hash 'GENESIS'."""
    audit.write({"agent_name": "a", "action_type": "CHAT"})
    data = json.loads(audit.log_path.read_text().strip())
    assert data["prev_hash"] == "GENESIS"


def test_chain_links_correctly(audit: AuditManager):
    """Write 3 entries and verify prev_hash links to entry_hash."""
    h1 = audit.write({"agent_name": "a", "action_type": "CHAT"})
    h2 = audit.write({"agent_name": "b", "action_type": "CHAT"})
    h3 = audit.write({"agent_name": "c", "action_type": "CHAT"})
    
    lines = audit.log_path.read_text().strip().split("\n")
    data1 = json.loads(lines[0])
    data2 = json.loads(lines[1])
    data3 = json.loads(lines[2])
    
    assert data2["prev_hash"] == h1
    assert data3["prev_hash"] == h2


def test_entry_hash_is_sha256(audit: AuditManager):
    """entry_hash is a 64-character hex string (SHA-256)."""
    h1 = audit.write({"agent_name": "a", "action_type": "CHAT"})
    assert len(h1) == 64
    # Ensure it's valid hex
    int(h1, 16)


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------

def test_verify_chain_passes_on_clean_log(audit: AuditManager):
    """verify_chain() returns valid=True on untampered log."""
    for _ in range(5):
        audit.write({"agent_name": "a", "action_type": "CHAT"})
        
    result = audit.verify_chain()
    assert result["valid"] is True
    assert result["total_entries"] == 5


def test_verify_chain_detects_tampering(audit: AuditManager):
    """verify_chain() detects manual edits to the log file."""
    audit.write({"agent_name": "a", "action_type": "CHAT", "outcome": "SUCCESS"})
    audit.write({"agent_name": "b", "action_type": "CHAT", "outcome": "SUCCESS"})
    audit.write({"agent_name": "c", "action_type": "CHAT", "outcome": "SUCCESS"})
    
    # Tamper with the second entry
    lines = audit.log_path.read_text().strip().split("\n")
    hacked_data = json.loads(lines[1])
    hacked_data["outcome"] = "FAILURE"  # change outcome without updating hashes
    lines[1] = json.dumps(hacked_data)
    audit.log_path.write_text("\n".join(lines) + "\n")
    
    result = audit.verify_chain()
    assert result["valid"] is False
    assert result["first_broken_at"] == 2
    assert "content hash mismatch" in result["error"]


# ---------------------------------------------------------------------------
# Redaction logic
# ---------------------------------------------------------------------------

def test_api_key_redacted_in_log(audit: AuditManager):
    """sk-ant-... formats are removed."""
    audit.write({
        "agent_name": "a",
        "action_type": "HTTP_REQUEST",
        "command_or_url": "curl -H 'Authorization: Bearer sk-ant-abc123xyz' google.com"
    })
    
    data = json.loads(audit.log_path.read_text().strip())
    assert "sk-ant-abc123xyz" not in data["command_or_url"]
    assert "[REDACTED:ANTHROPIC_KEY]" in data["command_or_url"]


def test_google_api_key_redacted(audit: AuditManager):
    """AIza... formats are removed."""
    audit.write({
        "agent_name": "a",
        "action_type": "HTTP_REQUEST",
        "command_or_url": "https://maps.googleapis.com/maps/api?key=AIzaSyABC123xyz"
    })
    
    data = json.loads(audit.log_path.read_text().strip())
    assert "AIzaSyABC123xyz" not in data["command_or_url"]
    assert "[REDACTED:GOOGLE_API_KEY]" in data["command_or_url"]


def test_dotenv_patterns_redacted(manager_with_env: AuditManager):
    """Values matching patterns extracted from .env are redacted."""
    manager_with_env.write({
        "agent_name": "a",
        "action_type": "TERMINAL_CMD",
        "command_or_url": "echo super_secret_12345 to file"
    })
    
    data = json.loads(manager_with_env.log_path.read_text().strip())
    assert "super_secret_12345" not in data["command_or_url"]
    assert "[REDACTED:MY_SECRET_KEY]" in data["command_or_url"]


# ---------------------------------------------------------------------------
# Querying and stats
# ---------------------------------------------------------------------------

def test_get_recent_returns_latest_first(audit: AuditManager):
    """get_recent(limit=3) returns 3 most recent entries, correctly ordered."""
    for i in range(10):
        audit.write({"agent_name": f"agent_{i}", "action_type": "CHAT"})
        
    recent = audit.get_recent(limit=3)
    assert len(recent) == 3
    assert recent[0]["seq"] == 10
    assert recent[1]["seq"] == 9
    assert recent[2]["seq"] == 8


def test_get_recent_filtered_by_action_type(audit: AuditManager):
    """get_recent(action_type=...) filters correctly."""
    for _ in range(5):
        audit.write({"agent_name": "a", "action_type": "FILE_READ"})
    for _ in range(3):
        audit.write({"agent_name": "a", "action_type": "SECURITY_VIOLATION"})
        
    recent = audit.get_recent(action_type="SECURITY_VIOLATION")
    assert len(recent) == 3
    for entry in recent:
        assert entry["action_type"] == "SECURITY_VIOLATION"


def test_get_violations_filters_by_time(audit: AuditManager):
    """get_violations(since_hours=24) returns recent violations."""
    audit.write({"agent_name": "a", "action_type": "SECURITY_VIOLATION"})
    audit.write({"agent_name": "b", "action_type": "SECURITY_VIOLATION"})
    
    violations = audit.get_violations(since_hours=24)
    assert len(violations) == 2


def test_get_stats_counts_correctly(audit: AuditManager):
    """get_stats() aggregates actions properly."""
    audit.write({"agent_name": "a", "action_type": "FILE_READ", "outcome": "SUCCESS"})
    audit.write({"agent_name": "b", "action_type": "SECURITY_VIOLATION", "outcome": "BLOCKED"})
    audit.write({"agent_name": "b", "action_type": "SECURITY_VIOLATION", "outcome": "BLOCKED"})
    
    stats = audit.get_stats()
    assert stats["total_actions"] == 3
    assert stats["violations"] == 2
    assert stats["blocked_attempts"] == 2
    assert stats["by_action_type"]["FILE_READ"] == 1
    assert stats["by_action_type"]["SECURITY_VIOLATION"] == 2
    assert set(stats["agents_active"]) == {"a", "b"}


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

def test_concurrent_writes_dont_corrupt(audit: AuditManager):
    """Multiple threads writing simultaneously maintain valid JSON-L and hash chain."""
    def worker():
        for _ in range(10):
            audit.write({"agent_name": "thread_agent", "action_type": "CHAT"})
            
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    # 5 threads * 10 writes = 50 entries
    result = audit.verify_chain()
    assert result["valid"] is True
    assert result["total_entries"] == 50
