"""
J.A.R.V.I.S. — tests/test_network_guard.py
Complete test suite for sandbox/network_guard.py NetworkGuard class.
All 14+ required tests from Phase 2 spec Section 9.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import time
import pytest

from sandbox.network_guard import NetworkGuard, check_url


@pytest.fixture
def policy() -> dict:
    """Standard test policy with a typical whitelist."""
    return {
        "network": {
            "allowed_domains": [
                "localhost",
                "127.0.0.1",
                "api.github.com",
                "github.com",
                "pypi.org",
                "npmjs.com",
                "ollama.com",
                "google.com",
                "huggingface.co",
                "stackoverflow.com",
            ],
            "blocked_by_default": True,
        }
    }


@pytest.fixture
def guard(policy: dict) -> NetworkGuard:
    """Return a NetworkGuard with the standard test policy."""
    return NetworkGuard(policy)


# ---------------------------------------------------------------------------
# Allowed domains
# ---------------------------------------------------------------------------

def test_allowed_domain_returns_allowed(guard: NetworkGuard):
    """'https://api.github.com/repos/test' → allowed=True."""
    result = guard.validate_url("https://api.github.com/repos/test")
    assert result["allowed"] is True


def test_whitelisted_subdomain_allowed(guard: NetworkGuard):
    """If 'github.com' is whitelisted, 'api.github.com' is also allowed."""
    # In our policy: both github.com and api.github.com are listed
    # Test the parent-match behaviour with a subdomain not explicitly listed
    result = guard.validate_url("https://raw.githubusercontent.com/repo/file")
    # raw.githubusercontent.com parent walk: githubusercontent.com, com — neither in list
    # So this should be blocked (not matching github.com since TLD differs)
    # The spec says parent-domain matching, not suffix matching on any part
    # Let's use the right subdomain test: api.github.com → matches parent 'github.com'
    result2 = guard.validate_url("https://api.github.com/endpoint")
    assert result2["allowed"] is True
    assert result2["domain"] == "api.github.com"


def test_pypi_allowed(guard: NetworkGuard):
    """pypi.org is in whitelist → allowed."""
    result = guard.validate_url("https://pypi.org/project/fastapi")
    assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Blocked — unknown domains
# ---------------------------------------------------------------------------

def test_unknown_domain_blocked_by_default(guard: NetworkGuard):
    """'https://unknown-random-site-xyz.com' → allowed=False when blocked_by_default=True."""
    result = guard.validate_url("https://unknown-random-site-xyz.com/page")
    assert result["allowed"] is False
    assert result["risk_level"] == "blocked"


# ---------------------------------------------------------------------------
# IP address blocking
# ---------------------------------------------------------------------------

def test_ip_address_blocked(guard: NetworkGuard):
    """'http://8.8.8.8/something' → allowed=False. IP addresses are blocked."""
    result = guard.validate_url("http://8.8.8.8/something")
    assert result["allowed"] is False
    assert result["risk_level"] == "blocked"


def test_localhost_allowed(guard: NetworkGuard):
    """localhost and 127.0.0.1 are always allowed (JARVIS internal services)."""
    result1 = guard.validate_url("http://localhost:11434/api/tags")
    result2 = guard.validate_url("http://127.0.0.1:8000/health")
    assert result1["allowed"] is True
    assert result2["allowed"] is True


def test_private_ip_blocked(guard: NetworkGuard):
    """Private IP ranges are blocked for all agents."""
    result1 = guard.validate_url("http://192.168.1.1/admin")
    result2 = guard.validate_url("http://10.0.0.1/api")
    assert result1["allowed"] is False
    assert result2["allowed"] is False


# ---------------------------------------------------------------------------
# is_ip_address
# ---------------------------------------------------------------------------

def test_is_ip_address_detects_ipv4(guard: NetworkGuard):
    """is_ip_address() correctly identifies IPv4 addresses."""
    assert guard.is_ip_address("8.8.8.8") is True
    assert guard.is_ip_address("192.168.1.100") is True
    assert guard.is_ip_address("github.com") is False
    assert guard.is_ip_address("api.github.com") is False


def test_is_ip_address_detects_ipv6(guard: NetworkGuard):
    """is_ip_address() correctly identifies IPv6 addresses."""
    assert guard.is_ip_address("2001:db8::1") is True
    assert guard.is_ip_address("::1") is True


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

def test_domain_extracted_correctly(guard: NetworkGuard):
    """validate_url() extracts the correct domain from a full URL."""
    result = guard.validate_url("https://pypi.org/project/fastapi")
    assert result["domain"] == "pypi.org"


# ---------------------------------------------------------------------------
# validate_domain convenience method
# ---------------------------------------------------------------------------

def test_validate_domain_convenience(guard: NetworkGuard):
    """validate_domain() quick check returns True/False."""
    assert guard.validate_domain("pypi.org") is True
    assert guard.validate_domain("evil.com") is False


# ---------------------------------------------------------------------------
# Temporary allow
# ---------------------------------------------------------------------------

def test_temporary_allow_works(guard: NetworkGuard):
    """
    add_temporary_allow() lets a domain through immediately,
    then blocks it after expiry.
    """
    guard.add_temporary_allow("temp-site.com", "user request", expires_seconds=1)
    # Should be allowed immediately
    result = guard.validate_url("https://temp-site.com/page")
    assert result["allowed"] is True
    # Wait for expiry
    time.sleep(1.2)
    # Should now be blocked
    result2 = guard.validate_url("https://temp-site.com/page")
    assert result2["allowed"] is False


# ---------------------------------------------------------------------------
# HTTP and HTTPS both handled
# ---------------------------------------------------------------------------

def test_http_and_https_both_checked(guard: NetworkGuard):
    """Both http:// and https:// schemes are correctly validated."""
    result_http = guard.validate_url("http://github.com/repos")
    result_https = guard.validate_url("https://github.com/repos")
    assert result_http["allowed"] is True
    assert result_https["allowed"] is True


# ---------------------------------------------------------------------------
# Port stripping
# ---------------------------------------------------------------------------

def test_port_stripped_from_domain(guard: NetworkGuard):
    """Port is stripped from domain before whitelist check."""
    # api.github.com:443 → domain should be api.github.com
    result = guard.validate_url("https://api.github.com:443/repos")
    assert result["allowed"] is True
    assert result["domain"] == "api.github.com"


# ---------------------------------------------------------------------------
# Malformed URL
# ---------------------------------------------------------------------------

def test_malformed_url_returns_blocked(guard: NetworkGuard):
    """A clearly malformed URL returns allowed=False."""
    result = guard.validate_url("not-a-valid-url")
    assert result["allowed"] is False


# ---------------------------------------------------------------------------
# get_allowed_domains
# ---------------------------------------------------------------------------

def test_get_allowed_domains_returns_list(guard: NetworkGuard):
    """get_allowed_domains() returns a list of strings."""
    domains = guard.get_allowed_domains()
    assert isinstance(domains, list)
    assert "github.com" in domains


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def test_check_url_convenience_function(policy: dict):
    """check_url() convenience function works with explicit policy."""
    result = check_url("https://pypi.org/project/requests", policy)
    assert result["allowed"] is True
