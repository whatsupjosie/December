"""Canonical permanent-preservation policy for Iteration Wallet and BlackBox.

This module is intentionally small and dependency-free so every active surface
can import one vocabulary and one set of state-normalization rules.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

PERMANENT_PRESERVATION_RULE = (
    "Once material is admitted into Iteration Wallet, the admitted content remains "
    "preserved. State, visibility, relationships, and trust may change, but Wallet "
    "has no operation that reduces or discards protected content."
)

BLACKBOX_PRESERVATION_RULE = (
    "Once BlackBox accepts a fact or evidentiary artifact, it remains preserved. "
    "Rotation, migration, repair, and checkpointing are additive operations."
)

RUNTIME_RESIDUE_RULE = (
    "Only program-created, non-authoritative operating residue may be cleaned, and "
    "only after its class, ownership, path, identity, age, and lack of authoritative "
    "references have been reverified. Uncertain material remains preserved."
)

PROTECTED_STATES = frozenset({
    "raw",
    "candidate",
    "prime",
    "archived",
    "retired",
    "quarantined",
    "banned",
    "legacy_externalized",
})

LEGACY_STATE_ALIASES = {
    "removed": "retired",
    "staging": "retired",
    "released": "legacy_externalized",
}

EXACT_OPERATION_LABELS = {
    "admit": "Admit",
    "retire_object": "Retire",
    "restore_retired_object": "Restore",
    "archive_object": "Archive",
    "quarantine": "Quarantine",
    "make_internal_copy": "Make internal copy",
    "issue_external_copy": "Issue external copy",
    "revoke_passkey": "Revoke passkey",
    "decommission_vault": "Decommission vault",
    "cleanup_runtime_residue": "Cleanup runtime residue",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_legacy_catalog(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return an additive vocabulary migration without dropping any catalog data.

    Original state labels are copied into ``legacy_state`` before normalization.
    The physical custody path is never changed by this function.  Legacy paths
    therefore remain inspectable and verifiable until a separately witnessed
    custody transition is implemented.
    """
    data = deepcopy(dict(payload))
    migrations: list[dict[str, Any]] = []
    for project in data.setdefault("projects", []):
        if not isinstance(project, dict):
            continue
        for section in project.setdefault("sections", []):
            if not isinstance(section, dict):
                continue
            for record in section.setdefault("files", []):
                if not isinstance(record, dict):
                    continue
                old_state = str(record.get("state") or "")
                new_state = LEGACY_STATE_ALIASES.get(old_state)
                if not new_state:
                    continue
                record.setdefault("legacy_state", old_state)
                record["state"] = new_state
                record.setdefault("preservation_migration", "permanent-preservation-v1")
                migrations.append(
                    {
                        "type": "VOCABULARY_STATE_NORMALIZED",
                        "project_id": project.get("id"),
                        "section_id": section.get("id"),
                        "object_id": record.get("id"),
                        "from_state": old_state,
                        "to_state": new_state,
                    }
                )
    if migrations:
        existing = data.setdefault("preservation_migrations", [])
        if not isinstance(existing, list):
            existing = []
            data["preservation_migrations"] = existing
        existing.append(
            {
                "schema": "iteration-wallet-preservation-migration/1",
                "completed_at": utc_now(),
                "record_count": len(migrations),
                "records": migrations,
                "physical_paths_changed": False,
                "content_bytes_changed": False,
            }
        )
    return data, migrations
