"""Bounded AI runtime discovery for host integration.

Discovery reads only configuration files explicitly supplied by the host. It does
not scan the whole machine, probe ports, contact endpoints, or sign into an AI.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DiscoveredAIProfile:
    profile_id: str
    backend: str
    model: str
    enabled: bool
    source_config: str
    endpoint_kind: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _endpoint_kind(endpoint: str | None) -> str:
    if not endpoint:
        return "not_declared"
    lowered = endpoint.lower()
    if "127.0.0.1" in lowered or "localhost" in lowered:
        return "local"
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return "remote_declared"
    return "other_declared"


def discover_ai_profiles(config_paths: Iterable[Path | str]) -> list[DiscoveredAIProfile]:
    found: list[DiscoveredAIProfile] = []
    for supplied in config_paths:
        path = Path(supplied).expanduser().resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles = data.get("profiles") or {}
        if not isinstance(profiles, dict):
            continue
        for profile_id, profile in sorted(profiles.items()):
            if not isinstance(profile, dict):
                continue
            found.append(
                DiscoveredAIProfile(
                    profile_id=str(profile_id),
                    backend=str(profile.get("backend") or "unknown"),
                    model=str(profile.get("model") or "unknown"),
                    enabled=bool(profile.get("enabled", False)),
                    source_config=path.name,
                    endpoint_kind=_endpoint_kind(profile.get("endpoint")),
                )
            )
    return found


def closed_discovery_summary(profiles: Iterable[DiscoveredAIProfile]) -> dict[str, object]:
    items = list(profiles)
    return {
        "view_mode": "bounded_ai_discovery",
        "profile_count": len(items),
        "enabled_count": sum(1 for item in items if item.enabled),
        "profiles": [
            {
                "profile_id": item.profile_id,
                "backend": item.backend,
                "model": item.model,
                "enabled": item.enabled,
                "endpoint_kind": item.endpoint_kind,
            }
            for item in items
        ],
        "network_probed": False,
        "system_wide_scan_performed": False,
        "sign_in_attempted": False,
        "human_approval_required_before_binding": True,
    }


@dataclass(frozen=True, slots=True)
class RuntimeTransition:
    profile_id: str
    previous_state: str
    current_state: str
    protected_subject_id: str
    human_approval_required: bool = True
    direct_modification_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AIRegistryMonitor:
    """Opt-in transition detector for explicitly registered AI profiles.

    The host supplies the probe callback. This class itself performs no network,
    process, registry, filesystem, or account scan.
    """

    def __init__(self, profiles: Iterable[DiscoveredAIProfile], *, protected_subject_id: str = "host:protected_application") -> None:
        self.profiles = tuple(profiles)
        self.protected_subject_id = protected_subject_id
        self._states: dict[str, bool] = {}

    def poll(self, probe) -> list[RuntimeTransition]:
        transitions: list[RuntimeTransition] = []
        for profile in self.profiles:
            current = bool(probe(profile))
            previous = self._states.get(profile.profile_id, False)
            self._states[profile.profile_id] = current
            if current and not previous:
                transitions.append(
                    RuntimeTransition(
                        profile_id=profile.profile_id,
                        previous_state="offline",
                        current_state="online",
                        protected_subject_id=self.protected_subject_id,
                    )
                )
        return transitions


def transition_to_blackbox_fields(transition: RuntimeTransition) -> dict[str, object]:
    """Safe fields a host may submit to BlackBox when a registered AI appears."""
    return {
        "event_type": "runtime.ai_profile_online",
        "subject_id": transition.protected_subject_id,
        "payload": {
            "profile_id": transition.profile_id,
            "status": transition.current_state,
            "decision": "human_approval_required_before_modification",
            "enabled": True,
        },
        "channel": "INT",
        "event_code": "LKA",
    }
