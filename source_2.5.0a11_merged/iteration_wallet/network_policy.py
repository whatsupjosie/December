"""Supported network exposure policy for the local Wallet service."""
from __future__ import annotations

import ipaddress


class NetworkPolicyError(ValueError):
    """Raised when a launch request would expose Wallet beyond loopback."""


def require_loopback_host(host: str) -> tuple[str, str]:
    """Return ``(bind_host, browser_host)`` for an explicitly local endpoint.

    Remote operation needs a separately designed transport, authentication,
    session, and recovery boundary. The current release therefore refuses
    wildcard, LAN, and public bindings instead of accidentally publishing a
    custody service.
    """
    raw = str(host or "").strip()
    if raw.lower() == "localhost":
        return "127.0.0.1", "localhost"
    candidate = raw.strip("[]")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise NetworkPolicyError(
            "Iteration Wallet currently supports loopback hosts only: localhost, 127.0.0.1, or ::1"
        ) from exc
    if not address.is_loopback:
        raise NetworkPolicyError(
            "Iteration Wallet refuses non-loopback binding until a dedicated remote-access boundary is implemented"
        )
    return candidate, "localhost" if address.version == 4 else "[::1]"
