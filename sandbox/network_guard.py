"""
J.A.R.V.I.S. — sandbox/network_guard.py
Network domain whitelist enforcement for all agent HTTP/HTTPS requests.
Prevents data exfiltration and unauthorized external connections.

Security principle: DENY BY DEFAULT, ALLOW BY EXCEPTION.
Only explicitly whitelisted domains are allowed.
IP addresses are always blocked (except localhost/127.0.0.1).
Private network ranges are blocked for all agents.

Author: Hitansu Parichha | Nisum Technologies
Phase 2 — Blueprint v5.0
"""

from __future__ import annotations

import ipaddress
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml

logger = logging.getLogger(__name__)

_SECURITY_POLICY_PATH = Path(__file__).parent / "jarvis_security.yaml"

# Localhost identifiers always allowed for JARVIS internal services
_ALWAYS_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Private/reserved IP network ranges (agents cannot reach these)
_PRIVATE_RANGES = [
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
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


class NetworkGuard:
    """
    Network domain whitelist enforcement for J.A.R.V.I.S.

    Maintains an allow-list of domains loaded from jarvis_security.yaml.
    All HTTP/HTTPS requests from agents must pass through validate_url()
    before being executed.

    Rules (applied in order):
      1. localhost / 127.0.0.1 always allowed (JARVIS internal services)
      2. IP addresses (non-localhost) always blocked
      3. Private network IPs always blocked
      4. Domain must be in whitelist (or parent domain must be whitelisted)
      5. If blocked_by_default=True and domain not whitelisted: BLOCK
    """

    def __init__(self, policy: dict) -> None:
        """
        Load network rules from the policy dict.

        Args:
            policy: The full parsed jarvis_security.yaml dict.
        """
        network_section = policy.get("network", {})
        self._allowed_domains: set[str] = set(network_section.get("allowed_domains", []))
        self._blocked_by_default: bool = network_section.get("blocked_by_default", True)

        # Temporary allows: dict[domain] = expires_at datetime
        self._temp_allows: dict[str, datetime] = {}

        logger.debug(
            "NetworkGuard initialised — %d domains whitelisted, blocked_by_default=%s",
            len(self._allowed_domains),
            self._blocked_by_default,
        )

    def _purge_expired_temp_allows(self) -> None:
        """Remove expired temporary allows before checking."""
        now = datetime.now(timezone.utc)
        expired = [d for d, exp in self._temp_allows.items() if now >= exp]
        for domain in expired:
            del self._temp_allows[domain]
            logger.debug("Temporary allow expired for domain: %s", domain)

    def validate_url(self, url: str) -> dict:
        """
        Validate whether an agent is allowed to connect to a given URL.

        Args:
            url: Full URL string (e.g., "https://api.github.com/repos/...")

        Returns:
            dict with keys:
              allowed (bool): True if the connection is permitted.
              domain (str): The extracted domain from the URL.
              reason (str): Human-readable explanation.
              risk_level (str): "safe", "caution", or "blocked".
        """
        # Purge expired temp allows before checking
        self._purge_expired_temp_allows()

        # Parse the URL
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname  # strips port automatically
        except Exception as exc:
            return {
                "allowed": False,
                "domain": url,
                "reason": f"Malformed URL — cannot parse: {exc}",
                "risk_level": "blocked",
            }

        if not hostname:
            return {
                "allowed": False,
                "domain": url,
                "reason": f"Cannot extract hostname from URL: {url}",
                "risk_level": "blocked",
            }

        domain = hostname.lower()

        # RULE 1: localhost / 127.0.0.1 always allowed (JARVIS internal)
        if domain in _ALWAYS_ALLOWED_HOSTS:
            return {
                "allowed": True,
                "domain": domain,
                "reason": "JARVIS internal service — always allowed.",
                "risk_level": "safe",
            }

        # RULE 2: IP addresses blocked (use ipaddress for robust detection)
        if self.is_ip_address(domain):
            # Check if it's a private IP
            if self.is_private_ip(domain):
                return {
                    "allowed": False,
                    "domain": domain,
                    "reason": (
                        f"IP address '{domain}' is in a private/reserved network range. "
                        "Agents cannot connect to private network addresses."
                    ),
                    "risk_level": "blocked",
                }
            return {
                "allowed": False,
                "domain": domain,
                "reason": (
                    f"IP address '{domain}' is not allowed. "
                    "Only domain names are permitted — no direct IP connections."
                ),
                "risk_level": "blocked",
            }

        # RULE 3: Check temporary allows (user-granted exceptions)
        if domain in self._temp_allows:
            return {
                "allowed": True,
                "domain": domain,
                "reason": f"Temporarily whitelisted domain: {domain}",
                "risk_level": "caution",
            }
        # Also check if parent of temp allow matches
        for temp_domain in list(self._temp_allows.keys()):
            if domain == temp_domain or domain.endswith("." + temp_domain):
                return {
                    "allowed": True,
                    "domain": domain,
                    "reason": f"Domain matches temporary allow for: {temp_domain}",
                    "risk_level": "caution",
                }

        # RULE 4: Check permanent whitelist — domain OR parent domain
        if self._is_in_whitelist(domain):
            return {
                "allowed": True,
                "domain": domain,
                "reason": f"Domain '{domain}' is in the permanent whitelist.",
                "risk_level": "safe",
            }

        # RULE 5: blocked_by_default — deny everything not explicitly allowed
        if self._blocked_by_default:
            return {
                "allowed": False,
                "domain": domain,
                "reason": (
                    f"Domain '{domain}' is not in the JARVIS network whitelist. "
                    "Add it to jarvis_security.yaml to permit access, "
                    "or use add_temporary_allow() for one-time access."
                ),
                "risk_level": "blocked",
            }

        # If blocked_by_default is False, allow unknown domains (not recommended)
        return {
            "allowed": True,
            "domain": domain,
            "reason": f"Domain '{domain}' allowed (blocked_by_default=False).",
            "risk_level": "caution",
        }

    def _is_in_whitelist(self, domain: str) -> bool:
        """
        Check if domain OR any parent domain is in the allowed_domains set.

        Example: 'api.github.com' is allowed if 'api.github.com' OR 'github.com'
        is in the whitelist.
        """
        # Direct match
        if domain in self._allowed_domains:
            return True

        # Parent domain match — walk up the domain hierarchy
        parts = domain.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self._allowed_domains:
                return True

        return False

    def validate_domain(self, domain: str) -> bool:
        """
        Quick check — just returns True/False for a domain string.

        Args:
            domain: Domain string without scheme or path.

        Returns:
            True if the domain is allowed, False otherwise.
        """
        self._purge_expired_temp_allows()

        if domain in _ALWAYS_ALLOWED_HOSTS:
            return True
        if self.is_ip_address(domain) and domain not in _ALWAYS_ALLOWED_HOSTS:
            return False
        if domain in self._temp_allows:
            return True
        return self._is_in_whitelist(domain)

    def is_ip_address(self, host: str) -> bool:
        """
        Returns True if the host string is an IP address (IPv4 or IPv6).

        Args:
            host: Host string extracted from URL.

        Returns:
            True if host is an IP address, False if it's a hostname.
        """
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def is_private_ip(self, host: str) -> bool:
        """
        Returns True if the IP is in a private or reserved network range.

        Private ranges: 192.168.x.x, 10.x.x.x, 172.16-31.x.x,
        169.254.x.x (link-local), 100.64.x.x (carrier-grade NAT).

        Args:
            host: IP address string.

        Returns:
            True if private/reserved, False if public.
        """
        try:
            addr = ipaddress.ip_address(host)
            return any(addr in net for net in _PRIVATE_RANGES)
        except ValueError:
            return False

    def add_temporary_allow(
        self,
        domain: str,
        reason: str,
        expires_seconds: int = 300,
    ) -> None:
        """
        Temporarily whitelist a domain for a specific task.

        Expires after the given number of seconds. Used when user explicitly
        says "Jarvis, access this website for me" for an unlisted domain.

        Args:
            domain: The domain to whitelist (without scheme, e.g. "temp-site.com").
            reason: Why this domain is being allowed (for audit purposes).
            expires_seconds: How many seconds until the allow expires (default 5 min).
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
        self._temp_allows[domain.lower()] = expires_at
        logger.info(
            "Temporary allow granted for '%s' (%s) — expires in %ds at %s",
            domain, reason, expires_seconds, expires_at.isoformat(),
        )

    def get_allowed_domains(self) -> list[str]:
        """
        Return the current whitelist for display.

        Returns:
            Combined list of permanent and active temporary allows.
        """
        self._purge_expired_temp_allows()
        permanent = sorted(self._allowed_domains)
        temp = [f"{d} (temp)" for d in sorted(self._temp_allows.keys())]
        return permanent + temp


def check_url(url: str, policy: Optional[dict] = None) -> dict:
    """
    Convenience function — create a NetworkGuard and validate a URL in one call.

    Args:
        url: Full URL string to validate.
        policy: Policy dict. If None, loads from jarvis_security.yaml.

    Returns:
        NetworkGuard.validate_url() result dict.
    """
    if policy is None:
        policy = _load_policy()
    guard = NetworkGuard(policy)
    return guard.validate_url(url)
