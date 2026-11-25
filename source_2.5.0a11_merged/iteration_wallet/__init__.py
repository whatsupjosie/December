"""Iteration Wallet — local-first, permanent-preservation generation custody.

The package root intentionally stays lightweight.  Public classes are loaded
lazily so installation diagnostics can run even when the separately owned
BlackBox dependency is missing or damaged.  Requesting a runtime class still
fails visibly if its real dependencies are unavailable; no fallback recorder
is provided.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

from .version import WALLET_VERSION

__version__ = WALLET_VERSION
__author__ = "Josie Curtsey Cobbley"
__license__ = "Proprietary"

_EXPORTS: dict[str, tuple[str, str]] = {
    "ActorIdentity": (".identity", "ActorIdentity"),
    "IdentityError": (".identity", "IdentityError"),
    "LocalIdentityProvider": (".identity", "LocalIdentityProvider"),
    "ActorKind": (".notification_manager", "ActorKind"),
    "AccessRequest": (".notification_manager", "AccessRequest"),
    "ApprovalRequest": (".notification_manager", "ApprovalRequest"),
    "Notification": (".notification_manager", "Notification"),
    "NotificationLevel": (".notification_manager", "NotificationLevel"),
    "NotificationManager": (".notification_manager", "NotificationManager"),
    "RequestClassification": (".notification_manager", "RequestClassification"),
    "RequestStatus": (".notification_manager", "RequestStatus"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = ["__version__", *_EXPORTS]
