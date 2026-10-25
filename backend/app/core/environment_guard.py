import urllib.parse
from typing import Optional, Set
import logging

logger = logging.getLogger("environment_guard")


class EnvironmentSafetyViolation(RuntimeError):
    """Raised when an endpoint URL fails the strict testnet environment validation."""
    pass


# Exact allowlist of verified Delta Exchange Testnet hosts
VERIFIED_TESTNET_HOSTS: Set[str] = {
    "cdn-ind.testnet.deltaex.org",
    "cdn.testnet.deltaex.org",
    "api.testnet.deltaex.org",
}

# Known production domains explicitly identified to prevent real-money trading
KNOWN_PRODUCTION_HOSTS: Set[str] = {
    "cdn.deltaex.org",
    "api.delta.exchange",
    "cdn.india.delta.exchange",
    "api.india.delta.exchange",
    "india.delta.exchange",
    "delta.exchange",
    "app.delta.exchange",
}


def validate_testnet_host(url: Optional[str]) -> str:
    """
    Validate that the given URL strictly targets a verified Delta Exchange Testnet host.
    
    Security guarantees:
    1. Rejects missing or non-string URLs.
    2. Enforces HTTPS scheme strictly (no insecure HTTP or other schemes).
    3. Forbids embedded credentials (username/password in URL).
    4. Normalizes hostname (lowercased, stripped of trailing dots and whitespace).
    5. Rejects non-standard ports.
    6. Rejects any hostname not explicitly present in VERIFIED_TESTNET_HOSTS.
    7. Specifically detects and flags production hosts.
    8. Defeats lookalike domains (e.g. 'cdn-ind.testnet.deltaex.org.evil.com').
    
    Returns:
        The normalized, validated hostname.
        
    Raises:
        EnvironmentSafetyViolation if the URL fails any check.
    """
    if not url or not isinstance(url, str):
        raise EnvironmentSafetyViolation(
            "Environment Safety Violation: Exchange API URL is missing or empty. Fails closed."
        )

    cleaned_url = url.strip()
    try:
        parsed = urllib.parse.urlsplit(cleaned_url)
    except Exception as exc:
        raise EnvironmentSafetyViolation(
            f"Environment Safety Violation: Malformed URL '{cleaned_url}': {exc}"
        )

    # 1. Scheme check
    if parsed.scheme.lower() != "https":
        raise EnvironmentSafetyViolation(
            f"Environment Safety Violation: Insecure scheme '{parsed.scheme}'. Only HTTPS is permitted."
        )

    # 2. Embedded credentials check
    if parsed.username or parsed.password:
        raise EnvironmentSafetyViolation(
            "Environment Safety Violation: URLs with embedded credentials/userinfo are strictly prohibited."
        )

    # 3. Hostname extraction and normalization
    hostname = (parsed.hostname or "").lower().strip().rstrip(".")
    if not hostname:
        raise EnvironmentSafetyViolation(
            f"Environment Safety Violation: URL '{cleaned_url}' lacks a valid hostname."
        )

    # 4. Port validation
    if parsed.port is not None and parsed.port != 443:
        raise EnvironmentSafetyViolation(
            f"Environment Safety Violation: Non-standard port '{parsed.port}' is forbidden for testnet API."
        )

    # 5. Check against known production hosts first for clear diagnostic
    if hostname in KNOWN_PRODUCTION_HOSTS:
        raise EnvironmentSafetyViolation(
            f"Security Violation: Production host '{hostname}' detected! "
            f"TokenIQ is strictly restricted to testnet. Live real-money trading is blocked."
        )

    # 6. Strict allowlist membership check
    if hostname not in VERIFIED_TESTNET_HOSTS:
        raise EnvironmentSafetyViolation(
            f"Environment Safety Violation: Host '{hostname}' is not in the verified testnet allowlist: "
            f"{sorted(list(VERIFIED_TESTNET_HOSTS))}. Connection refused."
        )

    return hostname
