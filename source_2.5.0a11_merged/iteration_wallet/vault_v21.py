"""
Iteration Wallet v2.1 — Section / Candidate / Prime Engine
==========================================================

This module adds the explicit Iteration Wallet product model without replacing
v2's existing vault.py runtime:

Vault
  Project
    Section
      Raw Sources
      Candidates
      Cradle / Prime
      Archive
      Retired
      Recovery Holding
      Metadata

The active engine runs only in strict canonical mode. OPEN starts a local Vault
session but does not create a general-purpose authority token. Protected actions
require a separately issued action/session/object-scoped one-use ceremony token.
Candidate-to-Prime promotion, Retire/Restore, LabCopy, and quarantine/derivative
admission use canonical transaction coordinators.

HARD RULE: Once material is admitted, its protected content remains preserved.
Wallet may change state, visibility, relationships, or trust, but it does not
provide an operation that reduces or discards protected content.

HARD RULE: Iteration Wallet never executes user-custodied material. The Vault is
locked clean-room storage, not the workbench. Experiments, builds, tests, and
program execution happen outside Iteration Wallet. The engine may only inspect
metadata, hashes, static text, review notes, and externally supplied test results.
"""

from __future__ import annotations

import json
import copy
import os
import hashlib
import uuid
import stat
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, List

from typing import Protocol


class WalletEvidenceWriter(Protocol):
    def write_event(self, event_type: str, summary: str, **extra: Any) -> Dict[str, Any]: ...
    def write_custody_event(self, event_type: str, summary: str, **extra: Any) -> Dict[str, Any]: ...
    def write_violation_event(self, event_type: str, summary: str, **extra: Any) -> Dict[str, Any]: ...
    def build_closed_evidence_summary(self, **filters: Any) -> Dict[str, Any]: ...
from iteration_wallet.ceremony import CeremonyTokenLedger, CeremonyTokenError
from iteration_wallet.custody_io import (
    ensure_private_directory,
    copy_exclusive_exact,
    move_custody_no_clobber,
    publish_no_clobber,
    relocate_to_transition_evidence,
    verified_regular_file,
    write_all,
)
from iteration_wallet.intake_capsule import portable_basename
from iteration_wallet.preservation import (
    PERMANENT_PRESERVATION_RULE,
    normalize_legacy_catalog,
)
from iteration_wallet.durable_io import (
    DurableIOError,
    atomic_json,
    ensure_within,
    file_lock,
    fsync_directory,
    strict_json_read,
)


PRESERVATION_RULE = PERMANENT_PRESERVATION_RULE
NO_EXECUTE_RULE = "Iteration Wallet never executes user-custodied material. External work requires a separately migrated, traceable copy-export protocol."
CANONICAL_COORDINATED_ACTIONS = frozenset({
    "retire_object",
    "restore_retired_object",
    "promote_candidate_to_prime",
    "quarantine",
    "admit_oubliette_derivative_as_candidate",
    "export_working_copy",
    "admit_labcopy_result_as_candidate",
})


class VaultError(Exception):
    """Raised for expected Iteration Wallet operation failures."""


def catalog_mutation(method):
    """Run one catalog mutation against freshly loaded durable state."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.catalog_transaction():
            return method(self, *args, **kwargs)
    return wrapped


def _bounded_display_text(
    label: str, value: str, *, maximum: int, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise VaultError(f"{label} must be text")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise VaultError(f"{label} is required")
    if len(normalized) > maximum:
        raise VaultError(f"{label} exceeds {maximum} characters")
    if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in normalized):
        raise VaultError(f"{label} contains control characters")
    return normalized


class VaultEngine:
    """Section-aware Iteration Wallet engine.

    Safety is provided by custody layout, copy-not-mutate behavior, exact state
    transitions, live-person custody ceremonies, and permanent preservation.
    """

    def __init__(self, vault_root: Path, blackbox: Optional[WalletEvidenceWriter] = None, *, strict_ceremony_tokens: bool = True, ceremony_token_ttl_seconds: int = 300):
        if strict_ceremony_tokens is not True:
            raise VaultError(
                "Non-strict ceremony mode has been retired from the active engine; "
                "use the canonical transaction coordinator."
            )
        self.root = Path(vault_root)
        self.state_file = self.root / "state_v21.json"
        self.catalog_lock_dir = self.root / ".catalog_locks"
        self.catalog_lock_path = self.catalog_lock_dir / "state_v21.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            ensure_within(
                self.root,
                self.catalog_lock_dir,
                label="catalog lock directory",
                error_type=VaultError,
            )
        except DurableIOError as exc:
            raise VaultError(str(exc)) from exc
        if self.catalog_lock_dir.is_symlink():
            raise VaultError("catalog lock directory cannot be a symlink")
        self.catalog_lock_dir.mkdir(parents=True, exist_ok=True)
        self._catalog_transaction_depth = 0
        self._catalog_read_depth = 0
        self.blackbox = blackbox
        self.strict_ceremony_tokens = True
        self.ceremony_token_ttl_seconds = max(5, min(int(ceremony_token_ttl_seconds or 300), 900))
        self.ceremony_ledger = CeremonyTokenLedger(self.root, blackbox=blackbox)
        self._is_open = False
        self._ceremony_token: Optional[str] = None
        self._open_session_id: Optional[str] = None
        self._state: Dict[str, Any] = self._load()

    def attach_blackbox(self, blackbox: WalletEvidenceWriter) -> None:
        """Attach shared BlackBox evidence writer after construction."""
        self.blackbox = blackbox
        self.ceremony_ledger.blackbox = blackbox

    # ─── persistence ──────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                data = strict_json_read(self.state_file)
                if not isinstance(data, dict):
                    raise VaultError("vault state is not a JSON object")
                data.setdefault("projects", [])
                data.setdefault("events", [])
                data.setdefault("evidence_outbox", [])
                data, migrations = normalize_legacy_catalog(data)
                if migrations:
                    atomic_json(self.state_file, data)
                return data
            except (DurableIOError, VaultError) as exc:
                raise VaultError(f"Could not load vault state: {exc}") from exc
        return {
            "schema": "iteration-wallet-v2.1",
            "projects": [],
            "events": [],
            "evidence_outbox": [],
        }

    def _save(self) -> None:
        if self._catalog_transaction_depth <= 0:
            raise VaultError(
                "Catalog writes require catalog_transaction(); refusing an unlocked state overwrite."
            )
        try:
            atomic_json(self.state_file, self._state)
        except DurableIOError as exc:
            raise VaultError(f"Could not durably save vault state: {exc}") from exc

    @contextmanager
    def catalog_transaction(self):
        """Serialize and refresh the monolithic catalog before mutation."""
        if self._catalog_transaction_depth > 0:
            self._catalog_transaction_depth += 1
            try:
                yield self
            finally:
                self._catalog_transaction_depth -= 1
            return
        try:
            with file_lock(self.catalog_lock_path):
                self._state = self._load()
                self._catalog_transaction_depth = 1
                try:
                    yield self
                finally:
                    self._catalog_transaction_depth = 0
        except DurableIOError as exc:
            raise VaultError(f"catalog transaction lock failed: {exc}") from exc

    def refresh_catalog(self) -> None:
        """Reload durable state under the catalog lock without mutating it."""
        if self._catalog_transaction_depth > 0 or self._catalog_read_depth > 0:
            return
        try:
            with file_lock(self.catalog_lock_path):
                self._state = self._load()
        except DurableIOError as exc:
            raise VaultError(f"catalog read lock failed: {exc}") from exc

    @contextmanager
    def catalog_snapshot(self):
        """Provide one coherent, freshly loaded read snapshot.

        Public reads must not remain stale merely because another process or
        long-lived runtime committed a catalog transaction. Nested reads share
        one snapshot; active mutations already own the stronger write lock.
        """
        if self._catalog_transaction_depth > 0 or self._catalog_read_depth > 0:
            self._catalog_read_depth += 1
            try:
                yield self
            finally:
                self._catalog_read_depth -= 1
            return
        try:
            with file_lock(self.catalog_lock_path):
                self._state = self._load()
                self._catalog_read_depth = 1
                try:
                    yield self
                finally:
                    self._catalog_read_depth = 0
        except DurableIOError as exc:
            raise VaultError(f"catalog read lock failed: {exc}") from exc

    # ─── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _uid() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _today() -> str:
        # Portable across Linux/macOS/Windows; unlike %-d.
        return date.today().strftime("%d %b %Y").lstrip("0")

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _safe_size(path_text: str, fallback: int = 0) -> int:
        measured: int | None = None
        try:
            path = Path(path_text)
            if path.exists() and path.is_file():
                measured = int(path.stat().st_size)
        except (OSError, TypeError, ValueError):
            measured = None
        if measured is not None:
            return measured
        try:
            return int(fallback or 0)
        except (TypeError, ValueError):
            return 0

    def _touch_access(self, record: Dict[str, Any], accessed_by: str = "system", action: str = "metadata") -> None:
        record["last_accessed_at"] = self._now()
        record["last_accessed_by"] = accessed_by or "system"
        record["last_access_action"] = action or "metadata"

    def _closed_catalog_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        project_id = record.get("project_id")
        section_id = record.get("section_id")
        file_id = record.get("id")
        safe = {
            "id": file_id,
            "name": record.get("name"),
            "state": record.get("state"),
            "custody_state": record.get("state"),
            "size_bytes": self._safe_size(record.get("vault_path", ""), record.get("size_bytes", 0)),
            "created_at": record.get("created_at"),
            "last_accessed_at": record.get("last_accessed_at") or record.get("created_at"),
            "last_accessed_by": record.get("last_accessed_by") or "unknown",
            "closed_view_note": record.get("closed_view_note", ""),
            "access_level": record.get("access_level", "protected"),
            "project_id": project_id,
            "section_id": section_id,
        }
        if self.blackbox:
            safe["blackbox"] = self.blackbox.build_closed_evidence_summary(
                project_id=project_id,
                section_id=section_id,
                file_id=file_id,
                limit=3,
            )
        else:
            safe["blackbox"] = None
        return safe

    def _section_blackbox_summary(self, project_id: str, section_id: str) -> Optional[Dict[str, Any]]:
        if not self.blackbox:
            return None
        return self.blackbox.build_closed_evidence_summary(
            project_id=project_id,
            section_id=section_id,
            limit=5,
        )

    def _log(self, event_type: str, desc: str, **extra: Any) -> Dict[str, Any]:
        """Commit local state and a durable canonical-evidence delivery intent.

        The outbox is recovery control state, not a second evidence authority.
        It makes a catalog mutation and its obligation to append canonical
        evidence one atomic catalog commit. Delivery may then catch up safely
        using a stable BBX1 idempotency key.
        """
        timestamp = self._now()
        event = {"type": event_type, "desc": desc, "ts": timestamp, **extra}
        self._state.setdefault("events", []).insert(0, event)
        self._state["events"] = self._state["events"][:1000]
        outbox_id = self._uid()
        outbox_item = {
            "outbox_id": outbox_id,
            "event_id": uuid.uuid4().hex,
            "stage_key": f"catalog-outbox:{outbox_id}",
            "event_type": event_type,
            "summary": desc,
            "created_at": timestamp,
            "status": "pending",
            "attempts": 0,
            "last_error": None,
            "project_id": extra.get("project_id"),
            "section_id": extra.get("section_id"),
            "file_id": extra.get("file_id"),
            "state": extra.get("state"),
            "details": dict(extra),
        }
        self._state.setdefault("evidence_outbox", []).append(outbox_item)
        self._save()
        report = self._flush_evidence_outbox_locked()
        return {
            "outbox_id": outbox_id,
            "status": "delivered" if not any(
                item.get("outbox_id") == outbox_id and item.get("status") == "pending"
                for item in self._state.get("evidence_outbox", [])
            ) else "pending",
            "delivery_report": report,
        }

    def _pending_evidence_items_loaded(self) -> List[Dict[str, Any]]:
        return [
            item for item in self._state.setdefault("evidence_outbox", [])
            if item.get("status") == "pending"
        ]

    def _flush_evidence_outbox_locked(self) -> Dict[str, Any]:
        if self._catalog_transaction_depth <= 0:
            raise VaultError("Evidence delivery requires catalog_transaction().")
        pending = list(self._pending_evidence_items_loaded())
        report: Dict[str, Any] = {
            "checked": len(pending),
            "delivered": 0,
            "pending": len(pending),
            "errors": [],
            "ack_persisted": True,
        }
        changed = False
        for item in pending:
            item["attempts"] = int(item.get("attempts") or 0) + 1
            changed = True
            if not self.blackbox:
                item["last_error"] = "canonical evidence writer unavailable"
                report["errors"].append({
                    "outbox_id": item.get("outbox_id"),
                    "error": item["last_error"],
                })
                continue
            try:
                receipt = self.blackbox.write_custody_event(
                    str(item["event_type"]),
                    str(item["summary"]),
                    project_id=item.get("project_id"),
                    section_id=item.get("section_id"),
                    file_id=item.get("file_id"),
                    state=item.get("state"),
                    event_id=item.get("event_id"),
                    stage_key=item.get("stage_key"),
                    local_event=item.get("event_type"),
                    details=dict(item.get("details") or {}),
                )
                item["status"] = "delivered"
                item["delivered_at"] = self._now()
                item["canonical_event_id"] = receipt.get("event_id")
                item["canonical_event_hash"] = receipt.get("event_hash")
                item["last_error"] = None
                report["delivered"] += 1
            except Exception as exc:
                item["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
                report["errors"].append({
                    "outbox_id": item.get("outbox_id"),
                    "error": item["last_error"],
                })
        if changed:
            try:
                self._save()
            except VaultError as exc:
                # The canonical append may already be durable. Keep the older
                # on-disk pending state so restart can idempotently acknowledge it.
                report["ack_persisted"] = False
                report["errors"].append({"outbox_ack": str(exc)})
                self._state = self._load()
        report["pending"] = len(self._pending_evidence_items_loaded())
        return report

    def flush_evidence_outbox(self) -> Dict[str, Any]:
        """Retry every pending canonical evidence delivery idempotently."""
        with self.catalog_transaction():
            return self._flush_evidence_outbox_locked()

    def get_evidence_outbox_status(self) -> Dict[str, Any]:
        with self.catalog_snapshot():
            items = copy.deepcopy(self._state.setdefault("evidence_outbox", []))
        pending_items = [item for item in items if item.get("status") == "pending"]
        delivered_items = [item for item in items if item.get("status") == "delivered"]
        return {
            "pending": len(pending_items),
            "delivered": len(delivered_items),
            "pending_items": pending_items,
            "delivery_is_canonical_evidence": False,
        }

    def assert_canonical_evidence_current(
        self,
        *,
        project_id: str,
        section_id: str,
        file_id: str,
    ) -> None:
        """Block trust expansion while relevant catalog evidence is pending."""
        self._flush_evidence_outbox_locked()
        blocking = []
        for item in self._pending_evidence_items_loaded():
            if item.get("project_id") != project_id:
                continue
            item_section = item.get("section_id")
            item_file = item.get("file_id")
            if item_section not in (None, section_id):
                continue
            if item_file not in (None, file_id):
                continue
            blocking.append(item)
        if blocking:
            kinds = sorted({str(item.get("event_type") or "UNKNOWN") for item in blocking})
            raise VaultError(
                "pending canonical evidence blocks trust expansion for this object: "
                + ", ".join(kinds)
            )

    def _blackbox_violation_event(self, event_type: str, desc: str, **extra: Any) -> None:
        if not self.blackbox:
            return
        self.blackbox.write_violation_event(event_type, desc, details=extra, **extra)

    def _project_dir(self, project_id: str) -> Path:
        return self.root / "projects" / project_id

    def _section_dir(self, project_id: str, section_id: str) -> Path:
        return self._project_dir(project_id) / "sections" / section_id

    def _compartment_dir(self, project_id: str, section_id: str, compartment: str) -> Path:
        return self._section_dir(project_id, section_id) / compartment

    def _safe_copy_name(self, file_id: str, src: Path) -> str:
        safe = portable_basename(src.name, fallback="artifact.bin", max_utf8_bytes=140)
        return f"{file_id}_{safe}"

    def _custody_destination_name(self, object_id: str, source_name: str) -> str:
        safe = portable_basename(source_name, fallback="artifact.bin", max_utf8_bytes=140)
        return f"{object_id}_{safe}"

    def _transition_evidence_root(self, project_id: str, section_id: str) -> Path:
        return self._compartment_dir(project_id, section_id, "metadata") / "custody_transition_evidence"

    def _copy_into(self, src: Path, dst_dir: Path, file_id: str) -> Path:
        """Copy one external regular file into a fresh custody path safely.

        The source is opened once with no-follow semantics, the destination is
        created exclusively, and partial destinations are preserved if copying
        fails so an interrupted ingest is visible rather than silently retried
        over unknown bytes.
        """
        if src.is_symlink():
            raise VaultError("Source material cannot be a symlink")
        if dst_dir.is_symlink():
            raise VaultError("Custody destination directory cannot be a symlink")
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / self._safe_copy_name(file_id, src)

        source_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            source_flags |= os.O_NOFOLLOW
        try:
            source_fd = os.open(src, source_flags)
        except OSError as exc:
            raise VaultError(f"Cannot open source material safely: {exc}") from exc

        destination_fd: int | None = None
        try:
            info = os.fstat(source_fd)
            if not stat.S_ISREG(info.st_mode):
                raise VaultError("Source material must be one regular file")
            try:
                destination_fd = os.open(
                    dst,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError as exc:
                raise VaultError(f"Custody destination already exists: {dst}") from exc
            except OSError as exc:
                raise VaultError(f"Cannot create custody destination safely: {exc}") from exc

            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                write_all(destination_fd, chunk, error_type=VaultError)
            os.fsync(destination_fd)
        finally:
            if destination_fd is not None:
                os.close(destination_fd)
            os.close(source_fd)
        fsync_directory(dst_dir)
        return dst

    def _require_open_token(
        self,
        token: str,
        *,
        action_key: Optional[str] = None,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        section_id: Optional[str] = None,
        object_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        proposal_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        if action_key not in CANONICAL_COORDINATED_ACTIONS:
            raise VaultError(
                f"Protected action {action_key!r} is not yet migrated to the canonical "
                "transaction protocol; no ceremony token was consumed."
            )
        if not self._is_open or not self._open_session_id:
            raise VaultError("Vault must be open")
        try:
            return self.ceremony_ledger.validate_and_consume(
                token,
                action_key=action_key,
                session_id=session_id,
                open_session_id=self._open_session_id,
                project_id=project_id,
                section_id=section_id,
                object_id=object_id,
                proposal_id=proposal_id,
                proposal_hash=proposal_hash,
            )
        except CeremonyTokenError as exc:
            raise VaultError(str(exc)) from exc

    @staticmethod
    def _raise_unmigrated_action(action_key: str) -> None:
        """Fail without consuming authority or touching custody.

        Unmigrated protected actions deliberately have no dormant mutation
        implementation in the active engine. Each action remains unavailable
        until a dedicated Wallet-owned transaction coordinator is complete and tested.
        """
        raise VaultError(
            f"Protected action {action_key!r} is not yet migrated to the canonical "
            "transaction protocol; no ceremony token was consumed and no custody change was attempted."
        )

    # ─── lookup ───────────────────────────────────────────────────────────

    def _get_project_loaded(self, project_id: str) -> Dict[str, Any]:
        for project in self._state["projects"]:
            if project["id"] == project_id:
                return project
        raise VaultError("Project not found")

    def _get_section_loaded(self, project_id: str, section_id: str) -> Dict[str, Any]:
        project = self._get_project_loaded(project_id)
        for section in project.setdefault("sections", []):
            if section["id"] == section_id:
                return section
        raise VaultError("Section not found")

    def _find_file_loaded(self, project_id: str, section_id: str, file_id: str) -> Dict[str, Any]:
        section = self._get_section_loaded(project_id, section_id)
        for file_record in section.setdefault("files", []):
            if file_record["id"] == file_id:
                return file_record
        raise VaultError("File not found")

    def _read_result(self, record: Dict[str, Any]) -> Dict[str, Any]:
        # Mutators operating under catalog_transaction need the live record.
        # Public reads receive a snapshot so callers cannot mutate durable state
        # by retaining a Python dictionary reference.
        return record if self._catalog_transaction_depth > 0 else copy.deepcopy(record)

    def get_project(self, project_id: str) -> Dict[str, Any]:
        with self.catalog_snapshot():
            return self._read_result(self._get_project_loaded(project_id))

    def get_section(self, project_id: str, section_id: str) -> Dict[str, Any]:
        with self.catalog_snapshot():
            return self._read_result(self._get_section_loaded(project_id, section_id))

    def _find_file(self, project_id: str, section_id: str, file_id: str) -> Dict[str, Any]:
        with self.catalog_snapshot():
            return self._read_result(self._find_file_loaded(project_id, section_id, file_id))

    # ─── projects and sections ────────────────────────────────────────────

    @catalog_mutation
    def create_project(self, name: str, path: str = "") -> Dict[str, Any]:
        name = _bounded_display_text("Project name", name, maximum=256)
        path = _bounded_display_text("Project path", path, maximum=4096, allow_empty=True)
        project_id = self._uid()
        project = {
            "id": project_id,
            "name": name,
            "path": path,
            "created_at": self._now(),
            "sections": [],
        }
        (self._project_dir(project_id) / "metadata").mkdir(parents=True, exist_ok=True)
        self._state["projects"].append(project)
        self._log("PROJECT_CREATED", f"Project created: {name}", project_id=project_id)
        return project

    @catalog_mutation
    def create_section(self, project_id: str, name: str, description: str = "") -> Dict[str, Any]:
        project = self.get_project(project_id)
        name = _bounded_display_text("Section name", name, maximum=256)
        description = _bounded_display_text(
            "Section description", description, maximum=4096, allow_empty=True
        )
        section_id = self._uid()
        section = {
            "id": section_id,
            "name": name,
            "description": description,
            "created_at": self._now(),
            "files": [],
            "prime": None,
            "archive": [],
        }
        for compartment in ("raw_sources", "candidates", "cradle", "archive", "retired", "quarantine", "recovery_holding", "metadata"):
            self._compartment_dir(project_id, section_id, compartment).mkdir(parents=True, exist_ok=True)
        project.setdefault("sections", []).append(section)
        self._log("SECTION_CREATED", f"Section created: {name}", project_id=project_id, section_id=section_id)
        return section

    # ─── open / lock ceremony ─────────────────────────────────────────────

    @catalog_mutation
    def open_vault(self) -> Dict[str, Any]:
        self._is_open = True
        self._ceremony_token = None
        self._open_session_id = uuid.uuid4().hex[:16]
        self._log("VAULT_OPENED", "Vault opened; local session started")
        return {
            "is_open": True,
            "open_session_id": self._open_session_id,
            "strict_ceremony_tokens": True,
            "general_authority_token_issued": False,
        }

    @catalog_mutation
    def lock_vault(self) -> Dict[str, Any]:
        revoked = self.ceremony_ledger.revoke_for_open_session(self._open_session_id or "", reason="vault locked")
        self._is_open = False
        self._ceremony_token = None
        self._open_session_id = None
        self._log("VAULT_LOCKED", "Vault locked; ceremony tokens invalidated", revoked_tokens=revoked)
        return {"is_open": False, "revoked_ceremony_tokens": revoked}

    def issue_ceremony_token(
        self,
        action_key: str,
        session_id: str,
        *,
        actor_id: Optional[str] = None,
        project_id: Optional[str] = None,
        section_id: Optional[str] = None,
        object_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        proposal_hash: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Issue a short-lived action/session-bound ceremony token.

        The raw token is returned once and never persisted. The token is scoped
        to one protected action and consumed by that action.
        """
        if action_key not in CANONICAL_COORDINATED_ACTIONS:
            raise VaultError(
                f"Protected action {action_key!r} is not yet migrated to the canonical "
                "transaction protocol; no ceremony token was created."
            )
        if not self._is_open or not self._open_session_id:
            raise VaultError("Vault must be open before issuing a ceremony token")
        try:
            return self.ceremony_ledger.issue_token(
                action_key=action_key,
                session_id=session_id,
                actor_id=actor_id,
                project_id=project_id,
                section_id=section_id,
                object_id=object_id,
                proposal_id=proposal_id,
                proposal_hash=proposal_hash,
                open_session_id=self._open_session_id,
                ttl_seconds=ttl_seconds or self.ceremony_token_ttl_seconds,
            )
        except CeremonyTokenError as exc:
            raise VaultError(str(exc)) from exc

    def revoke_ceremony_token(self, ceremony_token: str, reason: str = "manual revocation") -> Dict[str, Any]:
        try:
            return self.ceremony_ledger.revoke_token(ceremony_token, reason=reason)
        except CeremonyTokenError as exc:
            raise VaultError(str(exc)) from exc

    def list_ceremony_tokens(self) -> List[Dict[str, Any]]:
        return self.ceremony_ledger.list_tokens(include_hashes=False)

    # ─── adding materials ─────────────────────────────────────────────────

    @catalog_mutation
    def _add_file_to_section(
        self,
        project_id: str,
        section_id: str,
        file_path: str,
        state: str,
        compartment: str,
        notes: str = "",
    ) -> Dict[str, Any]:
        section = self.get_section(project_id, section_id)
        src = Path(file_path)
        if not src.exists():
            raise VaultError(f"File not found: {file_path}")
        if not src.is_file():
            raise VaultError(f"Path is not a file: {file_path}")
        file_id = self._uid()
        dst = self._copy_into(src, self._compartment_dir(project_id, section_id, compartment), file_id)
        record = {
            "id": file_id,
            "name": src.name,
            "original_path": str(src),
            "vault_path": str(dst),
            "project_id": project_id,
            "section_id": section_id,
            "state": state,
            "hash": self._sha256(dst),
            "size_bytes": int(dst.stat().st_size),
            "created_at": self._now(),
            "last_accessed_at": self._now(),
            "last_accessed_by": "system:add_material",
            "last_access_action": "ingest",
            "notes": notes,
            "closed_view_note": notes,
            "access_level": "protected",
            "staged": False,
            "quarantined": False,
            "banned": False,
            "promoted": False,
            "execution_allowed": False,
            "execution_policy": "never_execute_inside_iteration_wallet",
        }
        section.setdefault("files", []).append(record)
        self._log(
            "RAW_SOURCE_ADDED" if state == "raw" else "CANDIDATE_ADDED",
            f"{src.name} added as {state}",
            project_id=project_id,
            section_id=section_id,
            file_id=file_id,
        )
        return record

    def add_raw_source(self, project_id: str, section_id: str, file_path: str, notes: str = "") -> Dict[str, Any]:
        return self._add_file_to_section(project_id, section_id, file_path, "raw", "raw_sources", notes)

    def add_candidate(self, project_id: str, section_id: str, file_path: str, notes: str = "") -> Dict[str, Any]:
        return self._add_file_to_section(project_id, section_id, file_path, "candidate", "candidates", notes)

    # ─── retirement / restoration / quarantine ceremony ─────────────────

    # Retirement and restoration are protected state transitions. They are
    # available only through the Wallet-owned state-transition coordinator.
    # No direct public engine method can bypass identity, ceremony, journal,
    # canonical evidence, receipt verification, or restart reconciliation.

    @catalog_mutation
    def _transition_object_state_unchecked(
        self,
        project_id: str,
        section_id: str,
        object_id: str,
        *,
        action_key: str,
        source_state: str,
        target_state: str,
        source_path: str,
        destination_path: str,
        expected_hash: str,
        expected_size: int,
        transaction_id: str,
        reason: str = "",
        fault_hook: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Complete one authorized Retire or Restore transition without loss.

        Publication is no-clobber. The prior active directory entry is moved
        into private transition evidence, never discarded. A restart may call
        this method again with the same transaction identity; it recognizes
        and completes an interrupted publication without repeating authority.
        """
        if action_key not in {"retire_object", "restore_retired_object"}:
            raise VaultError("Unsupported state-transition action")
        if action_key == "retire_object":
            if target_state != "retired" or source_state not in {"raw", "candidate", "archived"}:
                raise VaultError("Retire supports Raw Source, Candidate, or Archive objects")
        else:
            if source_state != "retired" or target_state not in {"raw", "candidate", "archived"}:
                raise VaultError("Restore requires a retired Raw Source, Candidate, or Archive object")

        reason = _bounded_display_text("transition reason", reason, maximum=2000, allow_empty=True)
        record = self._find_file(project_id, section_id, object_id)
        if (
            record.get("state") == target_state
            and record.get("last_state_transition_id") == transaction_id
            and record.get("vault_path") == destination_path
        ):
            return record
        if record.get("state") != source_state:
            raise VaultError(
                f"Object state changed before {action_key}: expected {source_state!r}, "
                f"found {record.get('state')!r}"
            )
        if record.get("hash") != expected_hash:
            raise VaultError("Object hash changed before state transition")
        if int(record.get("size_bytes") or -1) != int(expected_size):
            raise VaultError("Object size changed before state transition")
        if record.get("vault_path") != source_path:
            raise VaultError("Object custody path changed before state transition")

        source_root = self._compartment_dir(
            project_id, section_id, self._compartment_for_state(source_state)
        )
        destination_root = self._compartment_dir(
            project_id, section_id, self._compartment_for_state(target_state)
        )
        evidence_root = self._transition_evidence_root(project_id, section_id)
        try:
            source = ensure_within(
                source_root, Path(source_path), label="state-transition source", error_type=VaultError
            )
            destination = ensure_within(
                destination_root, Path(destination_path), label="state-transition destination", error_type=VaultError
            )
        except DurableIOError as exc:
            raise VaultError(str(exc)) from exc
        expected_name = self._custody_destination_name(object_id, Path(source_path).name)
        if destination.name != expected_name:
            raise VaultError("State-transition destination name does not match the authorized object")
        ensure_private_directory(
            destination_root, error_type=VaultError, label="state-transition destination"
        )
        ensure_private_directory(
            evidence_root, error_type=VaultError, label="custody transition evidence root"
        )
        evidence_path = evidence_root / transaction_id / source.name

        source_present = source.exists() or source.is_symlink()
        destination_present = destination.exists() or destination.is_symlink()
        evidence_present = evidence_path.exists() or evidence_path.is_symlink()

        if destination_present:
            verified_regular_file(
                destination, expected_hash=expected_hash, expected_size=expected_size,
                error_type=VaultError, label="state-transition destination",
            )
            if source_present:
                if evidence_present:
                    raise VaultError(
                        "State transition has source, destination, and evidence entries; "
                        "manual reconciliation is required"
                    )
                verified_regular_file(
                    source, expected_hash=expected_hash, expected_size=expected_size,
                    error_type=VaultError, label="state-transition source",
                )
                evidence_path = relocate_to_transition_evidence(
                    source, evidence_root, transition_id=transaction_id,
                    error_type=VaultError, label="state-transition source",
                )
            else:
                if not evidence_present:
                    raise VaultError(
                        "State-transition destination exists but prior active path evidence is missing"
                    )
                verified_regular_file(
                    evidence_path, expected_hash=expected_hash, expected_size=expected_size,
                    error_type=VaultError, label="state-transition evidence",
                )
        else:
            if evidence_present:
                raise VaultError(
                    "State-transition evidence exists without the authorized destination"
                )
            verified_regular_file(
                source, expected_hash=expected_hash, expected_size=expected_size,
                error_type=VaultError, label="state-transition source",
            )
            movement = move_custody_no_clobber(
                source,
                destination,
                evidence_root=evidence_root,
                transition_id=transaction_id,
                expected_hash=expected_hash,
                expected_size=expected_size,
                error_type=VaultError,
                label="protected object",
            )
            evidence_path = Path(movement["transition_evidence_path"])

        if fault_hook:
            fault_hook("custody_published")

        section = self._get_section_loaded(project_id, section_id)
        archive = section.setdefault("archive", [])
        if source_state == "archived" and object_id in archive:
            archive[:] = [item for item in archive if item != object_id]
        if target_state == "archived" and object_id not in archive:
            archive.append(object_id)

        transitioned_at = self._now()
        history = record.setdefault("state_history", [])
        if not isinstance(history, list):
            raise VaultError("Object state history is not a list")
        history.append({
            "transaction_id": transaction_id,
            "action_key": action_key,
            "from_state": source_state,
            "to_state": target_state,
            "reason": reason,
            "transitioned_at": transitioned_at,
            "source_path": source_path,
            "destination_path": str(destination),
            "transition_evidence_path": str(evidence_path),
            "protected_content_preserved": True,
        })
        if action_key == "retire_object":
            record["retired_from_state"] = source_state
            record["retired_from_compartment"] = self._compartment_for_state(source_state)
            record["retired_at"] = transitioned_at
            record["retirement_reason"] = reason
            record["retirement_transaction_id"] = transaction_id
        else:
            record["restored_at"] = transitioned_at
            record["restoration_reason"] = reason
            record["restoration_transaction_id"] = transaction_id
        record["state"] = target_state
        record["vault_path"] = str(destination)
        record["last_state_transition_id"] = transaction_id
        record["last_state_transition_action"] = action_key
        record["transition_evidence_path"] = str(evidence_path)
        record["trust_locked"] = False
        record.pop("state_transition_reconciliation_required", None)
        self._log(
            "OBJECT_RETIRED" if action_key == "retire_object" else "RETIRED_OBJECT_RESTORED",
            (
                f"{record.get('name') or object_id} retired with protected content preserved"
                if action_key == "retire_object"
                else f"{record.get('name') or object_id} restored to {target_state}"
            ),
            project_id=project_id, section_id=section_id, file_id=object_id,
            transaction_id=transaction_id, from_state=source_state, to_state=target_state,
        )
        self._save()
        if fault_hook:
            fault_hook("mutation_committed")
        return record

    @catalog_mutation
    def _mark_state_transition_reconciliation_unchecked(
        self,
        project_id: str,
        section_id: str,
        object_id: str,
        *,
        transaction_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        record = self._find_file(project_id, section_id, object_id)
        record["trust_locked"] = True
        record["state_transition_reconciliation_required"] = {
            "transaction_id": transaction_id,
            "reason": str(reason)[:500],
            "recorded_at": self._now(),
        }
        self._log(
            "STATE_TRANSITION_RECONCILIATION_REQUIRED",
            f"{record.get('name') or object_id} requires state-transition reconciliation",
            project_id=project_id, section_id=section_id, file_id=object_id,
            transaction_id=transaction_id,
        )
        self._save()
        return record

    def quarantine_file(
        self,
        project_id: str,
        section_id: str,
        file_id: str,
        ceremony_token: str,
        reason: str = "",
        ban: bool = False,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Direct quarantine is unavailable; use OublietteTransactionCoordinator."""
        raise VaultError(
            "Quarantine must use the Wallet-owned Oubliette transaction coordinator; "
            "the direct engine path cannot mint canonical Human Intent evidence."
        )

    @staticmethod
    def _compartment_for_state(state: str) -> str:
        mapping = {
            "raw": "raw_sources",
            "candidate": "candidates",
            "prime": "cradle",
            "archived": "archive",
            "retired": "retired",
            "quarantined": "quarantine",
            "legacy_externalized": "recovery_holding",
        }
        try:
            return mapping[state]
        except KeyError as exc:
            raise VaultError(f"Unknown custody state: {state!r}") from exc

    @catalog_mutation
    def _attach_oubliette_inspection_unchecked(
        self,
        project_id: str,
        section_id: str,
        file_id: str,
        *,
        report_id: str,
        report_hash: str,
        target_sha256: str,
        coverage: str,
        finding_codes: list[str],
        warnings: list[str],
        canonical_event_id: str,
        canonical_event_hash: str,
    ) -> Dict[str, Any]:
        record = self._find_file(project_id, section_id, file_id)
        if record.get("hash") != target_sha256:
            raise VaultError("Oubliette report hash does not match the custodied object")
        entry = {
            "report_id": report_id,
            "report_hash": report_hash,
            "target_sha256": target_sha256,
            "coverage": coverage,
            "finding_codes": sorted(set(finding_codes)),
            "warnings": list(warnings),
            "canonical_event_id": canonical_event_id,
            "canonical_event_hash": canonical_event_hash,
        }
        inspections = record.setdefault("oubliette_inspections", [])
        existing = next((item for item in inspections if item.get("report_id") == report_id), None)
        if existing is not None:
            if existing != entry:
                raise VaultError("Oubliette report retry conflicts with catalog metadata")
            return record
        inspections.append(entry)
        record["latest_oubliette_report_id"] = report_id
        self._state.setdefault("events", []).insert(0, {
            "type": "OUBLIETTE_STATIC_INSPECTION_RECORDED",
            "desc": f"Static inspection recorded for {record['name']}",
            "ts": self._now(),
            "project_id": project_id,
            "section_id": section_id,
            "file_id": file_id,
            "report_id": report_id,
            "canonical_event_hash": canonical_event_hash,
        })
        self._state["events"] = self._state["events"][:1000]
        self._save()
        return record

    @catalog_mutation
    def _quarantine_file_unchecked(
        self,
        project_id: str,
        section_id: str,
        file_id: str,
        *,
        reason: str,
        report_id: str,
        report_hash: str,
        transaction_id: str,
        fault_hook: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Perform the custody move after external Wallet authorization.

        This first Oubliette crossing is intentionally limited to Raw Sources
        and Candidates.  Prime/archive transitions require their own
        explicit authority semantics and are not smuggled through this method.
        """
        record = self._find_file(project_id, section_id, file_id)
        if record.get("state") not in {"raw", "candidate"}:
            raise VaultError("Only a Raw Source or Candidate may enter Oubliette quarantine")
        if record.get("trust_locked") or record.get("custody_locked"):
            raise VaultError("Object is locked pending reconciliation")
        inspection = next(
            (item for item in record.get("oubliette_inspections", []) if item.get("report_id") == report_id),
            None,
        )
        if inspection is None or inspection.get("report_hash") != report_hash:
            raise VaultError("Quarantine requires the exact registered Oubliette inspection report")
        if inspection.get("target_sha256") != record.get("hash"):
            raise VaultError("Inspection report no longer matches the custodied bytes")

        previous_state = str(record["state"])
        source_root = self._compartment_dir(
            project_id, section_id, self._compartment_for_state(previous_state)
        )
        source = self._require_owned_custody_file(
            record.get("vault_path"), expected_compartment=source_root, label="quarantine object"
        )
        if self._sha256(source) != record.get("hash"):
            raise VaultError("Custodied bytes changed after inspection; refusing quarantine crossing")
        quarantine_root = self._compartment_dir(project_id, section_id, "quarantine")
        ensure_private_directory(
            quarantine_root,
            error_type=VaultError,
            label="Quarantine compartment",
        )
        destination = quarantine_root / self._custody_destination_name(file_id, source.name)
        transition = move_custody_no_clobber(
            source,
            destination,
            evidence_root=self._transition_evidence_root(project_id, section_id),
            transition_id=f"{transaction_id}.quarantine.{file_id}",
            expected_hash=str(record.get("hash") or ""),
            expected_size=int(source.stat().st_size),
            error_type=VaultError,
            label="quarantine object",
        )
        if fault_hook:
            fault_hook("file_moved")

        record["previous_state_before_quarantine"] = previous_state
        record["previous_vault_path_before_quarantine"] = str(source)
        record["vault_path"] = str(destination)
        record["state"] = "quarantined"
        record["quarantined"] = True
        record["quarantined_at"] = self._now()
        record["quarantine_reason"] = reason
        record["quarantine_report_id"] = report_id
        record["quarantine_report_hash"] = report_hash
        record["quarantine_operation_id"] = transaction_id
        record["quarantine_publication_mode"] = transition["publication_mode"]
        record["quarantine_transition_evidence_path"] = transition["transition_evidence_path"]
        record["execution_allowed"] = False
        self._state.setdefault("events", []).insert(0, {
            "type": "OBJECT_QUARANTINED",
            "desc": f"{record['name']} moved into fenced quarantine custody",
            "ts": self._now(),
            "project_id": project_id,
            "section_id": section_id,
            "file_id": file_id,
            "report_id": report_id,
            "reason": reason,
            "transaction_id": transaction_id,
        })
        self._state["events"] = self._state["events"][:1000]
        self._save()
        if fault_hook:
            fault_hook("mutation_committed")
        return record

    @catalog_mutation
    def _admit_intake_capsule_unchecked(
        self,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        *,
        capsule_path: str,
        capsule_id: str,
        manifest_hash: str,
        blob_sha256: str,
        blob_size: int,
        source_label: str,
        candidate_id: str,
        report_id: str,
        report_hash: str,
        transaction_id: str,
        reason: str,
        fault_hook: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Admit one immutable Wallet Intake Capsule as a new Candidate.

        The authority transaction depends only on Wallet-controlled capsule
        bytes.  The quarantined parent and capsule remain preserved; admission
        creates a distinct Candidate with explicit capsule/report lineage.
        """
        section = self.get_section(project_id, section_id)
        parent = self._find_file(project_id, section_id, parent_object_id)
        if parent.get("state") != "quarantined":
            raise VaultError("Capsule admission requires a preserved quarantined parent")
        if parent.get("custody_locked") or parent.get("trust_locked"):
            raise VaultError("Quarantined parent is locked pending reconciliation")

        intake_root = self.root / "intake_capsules" / "blobs"
        source = self._require_owned_custody_file(
            capsule_path,
            expected_compartment=intake_root,
            label="Wallet Intake Capsule blob",
        )
        if self._sha256(source) != blob_sha256 or source.stat().st_size != int(blob_size):
            raise VaultError("Wallet Intake Capsule bytes do not match the authorized manifest")

        safe_label = portable_basename(str(source_label or "intake.bin"), fallback="intake.bin", max_utf8_bytes=140)
        existing = next(
            (item for item in section.get("files", []) if item.get("id") == candidate_id),
            None,
        )
        candidates_root = self._compartment_dir(project_id, section_id, "candidates")
        staging_root = self._compartment_dir(project_id, section_id, "metadata") / "intake_capsule_admission_staging"
        for directory in (candidates_root, staging_root):
            if directory.is_symlink():
                raise VaultError(f"Capsule admission directory cannot be a symlink: {directory.name}")
            directory.mkdir(parents=True, exist_ok=True)

        final = candidates_root / self._custody_destination_name(candidate_id, safe_label)
        staging = staging_root / f"{candidate_id}.incoming"

        if existing is not None:
            if (
                existing.get("state") != "candidate"
                or existing.get("hash") != blob_sha256
                or existing.get("parent_quarantined_id") != parent_object_id
                or existing.get("wallet_intake_capsule_id") != capsule_id
                or existing.get("wallet_intake_manifest_hash") != manifest_hash
                or existing.get("admission_operation_id") != transaction_id
            ):
                raise VaultError("Existing capsule Candidate conflicts with journaled admission")
            candidate_path = self._require_owned_custody_file(
                existing.get("vault_path"),
                expected_compartment=candidates_root,
                label="admitted capsule Candidate",
            )
            if self._sha256(candidate_path) != blob_sha256:
                raise VaultError("Existing capsule Candidate bytes do not match admission hash")
            return existing

        if final.is_symlink() or staging.is_symlink():
            raise VaultError("Capsule admission destination cannot be a symlink")
        publication_mode = "preexisting_verified"
        if not final.exists():
            if not staging.exists():
                copy_exclusive_exact(
                    source,
                    staging,
                    expected_hash=blob_sha256,
                    expected_size=int(blob_size),
                    error_type=VaultError,
                    label="Wallet Intake Capsule",
                )
                fsync_directory(staging_root)
            elif self._sha256(staging) != blob_sha256 or staging.stat().st_size != int(blob_size):
                raise VaultError("Existing capsule staging evidence conflicts with admission journal")
            publication_mode = publish_no_clobber(
                staging,
                final,
                expected_hash=blob_sha256,
                expected_size=int(blob_size),
                error_type=VaultError,
                label="Wallet Intake Capsule Candidate",
            )
            fsync_directory(candidates_root)
        elif self._sha256(final) != blob_sha256 or final.stat().st_size != int(blob_size):
            raise VaultError("Capsule Candidate destination conflicts with admission journal")

        if fault_hook:
            fault_hook("file_copied")

        record = {
            "id": candidate_id,
            "name": safe_label,
            "original_path": f"wallet-intake://{capsule_id}/{safe_label}",
            "vault_path": str(final),
            "project_id": project_id,
            "section_id": section_id,
            "state": "candidate",
            "hash": blob_sha256,
            "size_bytes": int(blob_size),
            "created_at": self._now(),
            "last_accessed_at": self._now(),
            "last_accessed_by": "system:wallet_intake_capsule_admission",
            "last_access_action": "candidate_admission",
            "notes": reason,
            "closed_view_note": reason,
            "access_level": "protected",
            "staged": False,
            "quarantined": False,
            "banned": False,
            "promoted": False,
            "execution_allowed": False,
            "execution_policy": "never_execute_inside_iteration_wallet",
            "origin": "wallet_intake_capsule",
            "parent_quarantined_id": parent_object_id,
            "parent_quarantined_sha256": parent.get("hash"),
            "wallet_intake_capsule_id": capsule_id,
            "wallet_intake_manifest_hash": manifest_hash,
            "oubliette_derivative_report_id": report_id,
            "oubliette_derivative_report_hash": report_hash,
            "admission_operation_id": transaction_id,
            "admission_operation_ids": [transaction_id],
            "admission_publication_mode": publication_mode,
            "admission_staging_evidence_path": str(staging),
            "trust_status": "candidate_only_no_automatic_trust",
        }
        section.setdefault("files", []).append(record)
        parent.setdefault("derived_candidates", []).append({
            "candidate_id": candidate_id,
            "candidate_sha256": blob_sha256,
            "capsule_id": capsule_id,
            "manifest_hash": manifest_hash,
            "report_id": report_id,
            "operation_id": transaction_id,
        })
        self._state.setdefault("events", []).insert(0, {
            "type": "WALLET_INTAKE_CAPSULE_ADMITTED_AS_CANDIDATE",
            "desc": f"{safe_label} admitted as a new Candidate from immutable Wallet Intake",
            "ts": self._now(),
            "project_id": project_id,
            "section_id": section_id,
            "file_id": candidate_id,
            "parent_object_id": parent_object_id,
            "capsule_id": capsule_id,
            "report_id": report_id,
            "transaction_id": transaction_id,
        })
        self._state["events"] = self._state["events"][:1000]
        self._save()
        if fault_hook:
            fault_hook("mutation_committed")
        return record

    @catalog_mutation
    def _admit_labcopy_capsule_unchecked(
        self,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        *,
        capsule_path: str,
        capsule_id: str,
        manifest_hash: str,
        blob_sha256: str,
        blob_size: int,
        source_label: str,
        candidate_id: str,
        lab_id: str,
        transaction_id: str,
        reason: str,
        fault_hook: Optional[Any] = None,
        fault_stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Admit one immutable LabCopy result capsule as a new Candidate.

        The source generation remains untouched.  The returned laboratory bytes
        must already be held by Wallet Intake, and this method never reads the
        external laboratory path.  Candidate identity is precommitted by the
        protected transaction so retries resolve to the same object.
        """
        section = self.get_section(project_id, section_id)
        parent = self._find_file(project_id, section_id, parent_object_id)
        if parent.get("state") not in {"prime", "candidate"}:
            raise VaultError("LabCopy result admission requires the preserved exported generation")
        if parent.get("custody_locked") or parent.get("trust_locked"):
            raise VaultError("LabCopy parent is locked pending reconciliation")

        intake_root = self.root / "intake_capsules" / "blobs"
        source = self._require_owned_custody_file(
            capsule_path,
            expected_compartment=intake_root,
            label="LabCopy result Intake Capsule blob",
        )
        if self._sha256(source) != blob_sha256 or source.stat().st_size != int(blob_size):
            raise VaultError("LabCopy Intake Capsule bytes do not match the authorized manifest")

        safe_label = portable_basename(
            str(source_label or "lab-result.bin"),
            fallback="lab-result.bin",
            max_utf8_bytes=140,
        )
        existing = next(
            (item for item in section.get("files", []) if item.get("id") == candidate_id),
            None,
        )
        candidates_root = self._compartment_dir(project_id, section_id, "candidates")
        staging_root = (
            self._compartment_dir(project_id, section_id, "metadata")
            / "labcopy_result_admission_staging"
        )
        for directory in (candidates_root, staging_root):
            if directory.is_symlink():
                raise VaultError(f"LabCopy admission directory cannot be a symlink: {directory.name}")
            directory.mkdir(parents=True, exist_ok=True)

        final = candidates_root / self._custody_destination_name(candidate_id, safe_label)
        staging = staging_root / f"{candidate_id}.incoming"

        if existing is not None:
            if (
                existing.get("state") != "candidate"
                or existing.get("hash") != blob_sha256
                or existing.get("parent_generation_id") != parent_object_id
                or existing.get("parent_generation_sha256") != parent.get("hash")
                or existing.get("wallet_intake_capsule_id") != capsule_id
                or existing.get("wallet_intake_manifest_hash") != manifest_hash
                or existing.get("labcopy_id") != lab_id
            ):
                raise VaultError("Existing LabCopy Candidate conflicts with journaled admission")
            candidate_path = self._require_owned_custody_file(
                existing.get("vault_path"),
                expected_compartment=candidates_root,
                label="admitted LabCopy Candidate",
            )
            if self._sha256(candidate_path) != blob_sha256:
                raise VaultError("Existing LabCopy Candidate bytes do not match admission hash")
            operations = list(existing.get("admission_operation_ids") or [])
            original_operation = existing.get("admission_operation_id")
            if original_operation and original_operation not in operations:
                operations.append(original_operation)
            if transaction_id not in operations:
                operations.append(transaction_id)
                existing["admission_operation_ids"] = operations
                existing["last_admission_retry_at"] = self._now()
                self._save()
            return existing

        if final.is_symlink() or staging.is_symlink():
            raise VaultError("LabCopy admission destination cannot be a symlink")
        publication_mode = "preexisting_verified"
        if not final.exists():
            if not staging.exists():
                copy_exclusive_exact(
                    source,
                    staging,
                    expected_hash=blob_sha256,
                    expected_size=int(blob_size),
                    error_type=VaultError,
                    label="LabCopy result Intake Capsule",
                )
                fsync_directory(staging_root)
            elif self._sha256(staging) != blob_sha256 or staging.stat().st_size != int(blob_size):
                raise VaultError("Existing LabCopy staging evidence conflicts with admission journal")
            publication_mode = publish_no_clobber(
                staging,
                final,
                expected_hash=blob_sha256,
                expected_size=int(blob_size),
                error_type=VaultError,
                label="LabCopy result Candidate",
            )
            fsync_directory(candidates_root)
        elif self._sha256(final) != blob_sha256 or final.stat().st_size != int(blob_size):
            raise VaultError("LabCopy Candidate destination conflicts with admission journal")

        if fault_hook and fault_stage == "file_copied":
            fault_hook("file_copied")

        record = {
            "id": candidate_id,
            "name": safe_label,
            "original_path": f"wallet-labcopy://{lab_id}/{capsule_id}/{safe_label}",
            "vault_path": str(final),
            "project_id": project_id,
            "section_id": section_id,
            "state": "candidate",
            "hash": blob_sha256,
            "size_bytes": int(blob_size),
            "created_at": self._now(),
            "last_accessed_at": self._now(),
            "last_accessed_by": "system:labcopy_result_admission",
            "last_access_action": "candidate_admission",
            "notes": reason,
            "closed_view_note": reason,
            "access_level": "protected",
            "staged": False,
            "quarantined": False,
            "banned": False,
            "promoted": False,
            "execution_allowed": False,
            "execution_policy": "never_execute_inside_iteration_wallet",
            "origin": "labcopy_result_intake_capsule",
            "parent_generation_id": parent_object_id,
            "parent_generation_sha256": parent.get("hash"),
            "derived_from_hash": parent.get("hash"),
            "labcopy_id": lab_id,
            "wallet_intake_capsule_id": capsule_id,
            "wallet_intake_manifest_hash": manifest_hash,
            "admission_operation_id": transaction_id,
            "admission_publication_mode": publication_mode,
            "admission_staging_evidence_path": str(staging),
            "trust_status": "candidate_only_no_automatic_trust",
        }
        section.setdefault("files", []).append(record)
        parent.setdefault("labcopy_result_candidates", []).append({
            "candidate_id": candidate_id,
            "candidate_sha256": blob_sha256,
            "lab_id": lab_id,
            "capsule_id": capsule_id,
            "manifest_hash": manifest_hash,
            "operation_id": transaction_id,
        })
        self._state.setdefault("events", []).insert(0, {
            "type": "LABCOPY_RESULT_ADMITTED_AS_CANDIDATE",
            "desc": f"{safe_label} admitted as a new Candidate from LabCopy Intake",
            "ts": self._now(),
            "project_id": project_id,
            "section_id": section_id,
            "file_id": candidate_id,
            "parent_object_id": parent_object_id,
            "lab_id": lab_id,
            "capsule_id": capsule_id,
            "transaction_id": transaction_id,
        })
        self._state["events"] = self._state["events"][:1000]
        self._save()
        if fault_hook and fault_stage == "mutation_committed":
            fault_hook("mutation_committed")
        return record

    @catalog_mutation
    def _admit_oubliette_derivative_unchecked(
        self,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        *,
        derivative_path: str,
        derivative_sha256: str,
        derivative_size: int,
        candidate_id: str,
        report_id: str,
        report_hash: str,
        transaction_id: str,
        reason: str,
        fault_hook: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Admit a separately inspected derivative as a new Candidate.

        The quarantined parent remains untouched.  Incoming bytes are first
        copied into a non-candidate admission-staging compartment, hashed while copying,
        and only moved into Candidates after the precommitted hash matches.
        A mismatch is preserved as failed-admission evidence.
        """
        section = self.get_section(project_id, section_id)
        parent = self._find_file(project_id, section_id, parent_object_id)
        if parent.get("state") != "quarantined":
            raise VaultError("Derivative admission requires a preserved quarantined parent")
        if parent.get("custody_locked") or parent.get("trust_locked"):
            raise VaultError("Quarantined parent is locked pending reconciliation")

        existing = next(
            (item for item in section.get("files", []) if item.get("id") == candidate_id),
            None,
        )
        candidates_root = self._compartment_dir(project_id, section_id, "candidates")
        staging_root = self._compartment_dir(project_id, section_id, "metadata") / "oubliette_admission_staging"
        for directory in (candidates_root, staging_root):
            if directory.is_symlink():
                raise VaultError(f"Derivative admission directory cannot be a symlink: {directory.name}")
            directory.mkdir(parents=True, exist_ok=True)

        source = Path(derivative_path)
        final = candidates_root / self._safe_copy_name(candidate_id, source)
        staging = staging_root / f"{candidate_id}.incoming"

        if existing is not None:
            if (
                existing.get("state") != "candidate"
                or existing.get("hash") != derivative_sha256
                or existing.get("parent_quarantined_id") != parent_object_id
                or existing.get("oubliette_derivative_report_id") != report_id
                or existing.get("admission_operation_id") != transaction_id
            ):
                raise VaultError("Existing derivative Candidate conflicts with journaled admission")
            candidate_path = self._require_owned_custody_file(
                existing.get("vault_path"),
                expected_compartment=candidates_root,
                label="admitted derivative Candidate",
            )
            if self._sha256(candidate_path) != derivative_sha256:
                raise VaultError("Existing derivative Candidate bytes do not match admission hash")
            return existing

        if final.is_symlink():
            raise VaultError("Derivative Candidate destination cannot be a symlink")
        if staging.is_symlink():
            raise VaultError("Derivative staging evidence cannot be a symlink")

        publication_mode = "preexisting_verified"
        if not final.exists():
            if not staging.exists():
                copy_exclusive_exact(
                    source,
                    staging,
                    expected_hash=derivative_sha256,
                    expected_size=int(derivative_size),
                    error_type=VaultError,
                    label="inspected derivative",
                )
                fsync_directory(staging_root)
            else:
                if self._sha256(staging) != derivative_sha256 or staging.stat().st_size != int(derivative_size):
                    raise VaultError("Existing derivative staging evidence conflicts with admission journal")
            publication_mode = publish_no_clobber(
                staging,
                final,
                expected_hash=derivative_sha256,
                expected_size=int(derivative_size),
                error_type=VaultError,
                label="derivative Candidate",
            )
            fsync_directory(candidates_root)
        elif self._sha256(final) != derivative_sha256 or final.stat().st_size != int(derivative_size):
            raise VaultError("Derivative Candidate destination conflicts with admission journal")

        if fault_hook:
            fault_hook("file_copied")

        record = {
            "id": candidate_id,
            "name": source.name,
            "original_path": str(source),
            "vault_path": str(final),
            "project_id": project_id,
            "section_id": section_id,
            "state": "candidate",
            "hash": derivative_sha256,
            "size_bytes": int(derivative_size),
            "created_at": self._now(),
            "last_accessed_at": self._now(),
            "last_accessed_by": "system:oubliette_derivative_admission",
            "last_access_action": "candidate_admission",
            "notes": reason,
            "closed_view_note": reason,
            "access_level": "protected",
            "staged": False,
            "quarantined": False,
            "banned": False,
            "promoted": False,
            "execution_allowed": False,
            "execution_policy": "never_execute_inside_iteration_wallet",
            "origin": "oubliette_cleared_derivative",
            "parent_quarantined_id": parent_object_id,
            "parent_quarantined_sha256": parent.get("hash"),
            "oubliette_derivative_report_id": report_id,
            "oubliette_derivative_report_hash": report_hash,
            "admission_operation_id": transaction_id,
            "admission_publication_mode": publication_mode,
            "admission_staging_evidence_path": str(staging),
            "trust_status": "candidate_only_no_automatic_trust",
        }
        section.setdefault("files", []).append(record)
        parent.setdefault("derived_candidates", []).append({
            "candidate_id": candidate_id,
            "candidate_sha256": derivative_sha256,
            "report_id": report_id,
            "operation_id": transaction_id,
        })
        self._state.setdefault("events", []).insert(0, {
            "type": "OUBLIETTE_DERIVATIVE_ADMITTED_AS_CANDIDATE",
            "desc": f"{source.name} admitted as a new Candidate derived from quarantined material",
            "ts": self._now(),
            "project_id": project_id,
            "section_id": section_id,
            "file_id": candidate_id,
            "parent_object_id": parent_object_id,
            "report_id": report_id,
            "transaction_id": transaction_id,
        })
        self._state["events"] = self._state["events"][:1000]
        self._save()
        if fault_hook:
            fault_hook("mutation_committed")
        return record

    # ─── Prime promotion ──────────────────────────────────────────────────

    def _require_owned_custody_file(
        self,
        path_text: Any,
        *,
        expected_compartment: Path,
        label: str,
    ) -> Path:
        if not path_text:
            raise VaultError(f"{label} has no custody path")
        path = Path(str(path_text))
        if path.is_symlink():
            raise VaultError(f"{label} custody path cannot be a symlink")
        if expected_compartment.is_symlink():
            raise VaultError(f"{label} compartment cannot be a symlink")
        try:
            resolved = ensure_within(
                expected_compartment, path, label=f"{label} custody path",
                error_type=VaultError,
            )
        except DurableIOError as exc:
            raise VaultError(str(exc)) from exc
        if not resolved.is_file():
            raise VaultError(f"{label} custody file is missing")
        return resolved

    def promote_to_prime(
        self,
        project_id: str,
        section_id: str,
        candidate_id: str,
        ceremony_token: str,
        reason: str = "",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible direct promotion path.

        The integrated public route uses ``PromotionTransactionCoordinator`` so
        authorization, journal state, custody mutation, and canonical evidence
        are recoverable as one protocol. This method remains for existing local
        engine callers and inherited tests.
        """
        if self.strict_ceremony_tokens:
            raise VaultError(
                "Strict Prime promotion must use the transaction coordinator; "
                "direct engine promotion cannot mint canonical Human Intent evidence."
            )
        self._require_open_token(
            ceremony_token,
            action_key="promote_candidate_to_prime",
            session_id=session_id,
            project_id=project_id,
            section_id=section_id,
            object_id=candidate_id,
        )
        return self._promote_candidate_to_prime_unchecked(
            project_id, section_id, candidate_id, reason=reason
        )

    @catalog_mutation
    def _promote_candidate_to_prime_unchecked(
        self,
        project_id: str,
        section_id: str,
        candidate_id: str,
        *,
        reason: str = "",
        transaction_id: Optional[str] = None,
        fault_hook: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Perform only the custody mutation after external authorization.

        This private method never consumes a token and must only be called by a
        path that has already passed Wallet identity, Gatekeeper, and scoped
        ceremony checks. ``fault_hook`` exists solely for deterministic crash
        campaigns and is never exposed through the API.
        """
        section = self.get_section(project_id, section_id)
        candidate = self._find_file(project_id, section_id, candidate_id)
        if candidate.get("state") not in ("candidate", "raw"):
            raise VaultError("Only a candidate/raw source can be promoted to Prime")
        if candidate.get("trust_locked"):
            raise VaultError("Candidate is trust-locked pending reconciliation")

        old_prime_id = section.get("prime")
        if old_prime_id:
            old_prime = self._find_file(project_id, section_id, old_prime_id)
            cradle_source = self._compartment_dir(project_id, section_id, "cradle")
            old_src = self._require_owned_custody_file(
                old_prime.get("vault_path"),
                expected_compartment=cradle_source,
                label="former Prime",
            )
            archive_dir = self._compartment_dir(project_id, section_id, "archive")
            if archive_dir.is_symlink():
                raise VaultError("Archive compartment cannot be a symlink")
            archive_dir.mkdir(parents=True, exist_ok=True)
            transition_key = str(transaction_id or f"legacy-{uuid.uuid4().hex}")
            old_dst = archive_dir / self._custody_destination_name(str(old_prime_id), old_src.name)
            old_transition = move_custody_no_clobber(
                old_src,
                old_dst,
                evidence_root=self._transition_evidence_root(project_id, section_id),
                transition_id=f"{transition_key}.archive.{old_prime_id}",
                expected_hash=str(old_prime.get("hash") or self._sha256(old_src)),
                expected_size=int(old_src.stat().st_size),
                error_type=VaultError,
                label="former Prime",
            )
            old_prime["vault_path"] = str(old_dst)
            old_prime["archive_publication_mode"] = old_transition["publication_mode"]
            old_prime["archive_transition_evidence_path"] = old_transition["transition_evidence_path"]
            old_prime["state"] = "archived"
            old_prime["archived_at"] = self._now()
            if old_prime_id not in section.setdefault("archive", []):
                section["archive"].append(old_prime_id)
            if fault_hook:
                fault_hook("old_prime_archived")

        source_compartment = self._compartment_dir(
            project_id,
            section_id,
            "raw_sources" if candidate.get("state") == "raw" else "candidates",
        )
        cand_src = self._require_owned_custody_file(
            candidate.get("vault_path"),
            expected_compartment=source_compartment,
            label="promotion candidate",
        )
        cradle_dir = self._compartment_dir(project_id, section_id, "cradle")
        if cradle_dir.is_symlink():
            raise VaultError("Cradle compartment cannot be a symlink")
        cradle_dir.mkdir(parents=True, exist_ok=True)
        transition_key = str(transaction_id or f"legacy-{uuid.uuid4().hex}")
        prime_dst = cradle_dir / self._custody_destination_name(candidate_id, cand_src.name)
        prime_transition = move_custody_no_clobber(
            cand_src,
            prime_dst,
            evidence_root=self._transition_evidence_root(project_id, section_id),
            transition_id=f"{transition_key}.prime.{candidate_id}",
            expected_hash=str(candidate.get("hash") or self._sha256(cand_src)),
            expected_size=int(cand_src.stat().st_size),
            error_type=VaultError,
            label="promotion candidate",
        )
        candidate["vault_path"] = str(prime_dst)
        candidate["promotion_publication_mode"] = prime_transition["publication_mode"]
        candidate["promotion_transition_evidence_path"] = prime_transition["transition_evidence_path"]

        candidate["state"] = "prime"
        candidate["promoted"] = True
        candidate["promoted_at"] = self._now()
        candidate["promotion_reason"] = reason
        section["prime"] = candidate_id
        event = {
            "type": "PRIME_PROMOTED",
            "desc": f"{candidate['name']} promoted to Prime",
            "ts": self._now(),
            "project_id": project_id,
            "section_id": section_id,
            "file_id": candidate_id,
            "reason": reason,
            "transaction_id": transaction_id,
        }
        self._state.setdefault("events", []).insert(0, event)
        self._state["events"] = self._state["events"][:1000]
        self._save()
        if fault_hook:
            fault_hook("mutation_committed")
        return candidate

    @catalog_mutation
    def review_candidate(
        self,
        project_id: str,
        section_id: str,
        candidate_id: str,
        verdict: str,
        summary: str = "",
        strengths: Optional[list[str]] = None,
        risks: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """Attach a Prime-readiness review to a Candidate.

        This is the AI/helper lane: evaluate and advise. It never promotes.
        Promotion still requires OPEN + ceremony token + explicit promote_to_prime.
        """
        candidate = self._find_file(project_id, section_id, candidate_id)
        if candidate.get("state") != "candidate":
            raise VaultError("Only Candidates can receive Prime-readiness reviews")
        verdict = (verdict or "needs_review").strip().lower().replace(" ", "_")
        allowed = {"ready", "not_ready", "needs_review", "donor_material"}
        if verdict not in allowed:
            raise VaultError(f"Review verdict must be one of: {', '.join(sorted(allowed))}")
        review = {
            "id": self._uid(),
            "candidate_id": candidate_id,
            "verdict": verdict,
            "summary": summary.strip(),
            "strengths": strengths or [],
            "risks": risks or [],
            "created_at": self._now(),
        }
        candidate.setdefault("reviews", []).append(review)
        candidate["last_review_verdict"] = verdict
        metadata_dir = self._compartment_dir(project_id, section_id, "metadata") / "candidate_reviews"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        (metadata_dir / f"{candidate_id}_{review['id']}.json").write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
        self._log("CANDIDATE_REVIEWED", f"{candidate['name']} reviewed: {verdict}", project_id=project_id, section_id=section_id, file_id=candidate_id, verdict=verdict)
        return review

    def export_working_copy(self, project_id: str, section_id: str, file_id: str, output_dir: str, ceremony_token: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Unavailable until traceable copy export has a canonical coordinator."""
        self._raise_unmigrated_action("export_working_copy")


    # ─── execution boundary / observational analysis ───────────────────────

    @catalog_mutation
    def attach_external_test_results(
        self,
        project_id: str,
        section_id: str,
        candidate_id: str,
        summary: str,
        passed: Optional[bool] = None,
        source: str = "external",
        artifacts: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """Attach externally generated test/build results without running code.

        Iteration Wallet may reason about results created outside the Vault. It
        does not run the candidate, run the project tests, or invoke a sandbox.
        """
        candidate = self._find_file(project_id, section_id, candidate_id)
        if candidate.get("state") not in ("candidate", "prime", "archived", "retired", "raw"):
            raise VaultError("External results can only be attached to custodied material")
        result = {
            "id": self._uid(),
            "candidate_id": candidate_id,
            "summary": summary.strip(),
            "passed": passed,
            "source": source.strip() or "external",
            "artifacts": artifacts or [],
            "observational_only": True,
            "created_at": self._now(),
        }
        candidate.setdefault("external_test_results", []).append(result)
        metadata_dir = self._compartment_dir(project_id, section_id, "metadata") / "external_results"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        (metadata_dir / f"{candidate_id}_{result['id']}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self._log("EXTERNAL_RESULTS_ATTACHED", f"External results attached for {candidate['name']}", project_id=project_id, section_id=section_id, file_id=candidate_id, source=result["source"])
        return result

    # ─── custody verification / incident detection ──────────────────────────

    def verify_custody_integrity(self) -> Dict[str, Any]:
        """Check stored custody records against files and hashes.

        This method never repairs content. It reports suspected custody breaks and
        writes BlackBox violation events when a custodied object is missing or
        changed without a custody ceremony.
        """
        incidents: List[Dict[str, Any]] = []
        for project in self._state.setdefault("projects", []):
            project_id = project.get("id")
            for section in project.setdefault("sections", []):
                section_id = section.get("id")
                prime_id = section.get("prime")
                for record in section.setdefault("files", []):
                    file_id = record.get("id")
                    state = record.get("state")
                    path_text = record.get("vault_path") or ""
                    if not path_text:
                        incident = {
                            "type": "MISSING_CUSTODY_PATH",
                            "project_id": project_id,
                            "section_id": section_id,
                            "file_id": file_id,
                            "name": record.get("name"),
                            "state": state,
                            "vault_path": "",
                        }
                        incidents.append(incident)
                        self._blackbox_violation_event(
                            "MISSING_CUSTODY_PATH",
                            f"Custodied object has no protected path: {record.get('name')}",
                            **incident,
                        )
                        continue
                    path = Path(path_text)
                    if not path.exists():
                        event_type = "MISSING_PRIME_OBJECT" if file_id == prime_id else "MISSING_CUSTODY_OBJECT"
                        incident = {
                            "type": event_type,
                            "project_id": project_id,
                            "section_id": section_id,
                            "file_id": file_id,
                            "name": record.get("name"),
                            "state": state,
                            "vault_path": path_text,
                        }
                        incidents.append(incident)
                        self._blackbox_violation_event(
                            event_type,
                            f"Custodied object missing: {record.get('name')}",
                            **incident,
                        )
                        continue
                    expected_hash = record.get("hash")
                    actual_hash = self._sha256(path)
                    if expected_hash and actual_hash != expected_hash:
                        event_type = "PRIME_HASH_MISMATCH" if file_id == prime_id else "HASH_MISMATCH"
                        incident = {
                            "type": event_type,
                            "project_id": project_id,
                            "section_id": section_id,
                            "file_id": file_id,
                            "name": record.get("name"),
                            "state": state,
                            "vault_path": path_text,
                            "expected_hash": expected_hash,
                            "actual_hash": actual_hash,
                        }
                        incidents.append(incident)
                        self._blackbox_violation_event(
                            event_type,
                            f"Custodied object hash mismatch: {record.get('name')}",
                            **incident,
                        )
        return {
            "ok": not incidents,
            "incident_count": len(incidents),
            "incidents": incidents,
        }

    # ─── views ────────────────────────────────────────────────────────────

    def get_section_view(self, project_id: str, section_id: str) -> Dict[str, Any]:
        """Return section view with closed-state privacy enforcement.

        When the Vault is closed, this returns a catalog-only view: names, state,
        size, created/last-accessed metadata, who last accessed, and the explicit
        closed-view note. It must not expose contents, vault paths, original paths,
        file hashes, reviews, external results, or protected action surfaces.

        When the Vault is open, existing callers receive the full compartment view.
        """
        if not self._is_open:
            return self.get_closed_catalog_view(project_id, section_id)
        return self.get_open_section_view(project_id, section_id)

    def get_open_section_view(self, project_id: str, section_id: str) -> Dict[str, Any]:
        section = self.get_section(project_id, section_id)
        files = section.setdefault("files", [])
        archive_ids = set(section.setdefault("archive", []))
        return {
            "project_id": project_id,
            "section_id": section_id,
            "name": section["name"],
            "view_mode": "open_full",
            "protected_contents_visible": True,
            "raw_sources": [f for f in files if f.get("state") == "raw"],
            "candidates": [f for f in files if f.get("state") == "candidate"],
            "cradle": self._find_file(project_id, section_id, section["prime"]) if section.get("prime") else None,
            "archive": [f for f in files if f.get("state") == "archived" or f.get("id") in archive_ids],
            "retired": [f for f in files if f.get("state") == "retired"],
            "quarantine": [f for f in files if f.get("state") in ("quarantined", "banned")],
            "recovery_holding": [f for f in files if f.get("state") == "legacy_externalized"],
            "metadata": {
                "created_at": section.get("created_at"),
                "description": section.get("description", ""),
                "file_count": len(files),
            },
            "blackbox": self._section_blackbox_summary(project_id, section_id),
            "is_vault_open": self._is_open,
        }

    def get_closed_catalog_view(self, project_id: str, section_id: str) -> Dict[str, Any]:
        section = self.get_section(project_id, section_id)
        files = section.setdefault("files", [])
        archive_ids = set(section.setdefault("archive", []))

        def safe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [self._closed_catalog_record(record) for record in records]

        return {
            "project_id": project_id,
            "section_id": section_id,
            "name": section["name"],
            "view_mode": "closed_catalog",
            "protected_contents_visible": False,
            "closed_view_policy": {
                "allowed_fields": [
                    "id",
                    "name",
                    "state",
                    "size_bytes",
                    "created_at",
                    "last_accessed_at",
                    "last_accessed_by",
                    "closed_view_note",
                    "access_level",
                    "blackbox",
                ],
            },
            "raw_sources": safe([f for f in files if f.get("state") == "raw"]),
            "candidates": safe([f for f in files if f.get("state") == "candidate"]),
            "cradle": self._closed_catalog_record(self._find_file(project_id, section_id, section["prime"])) if section.get("prime") else None,
            "archive": safe([f for f in files if f.get("state") == "archived" or f.get("id") in archive_ids]),
            "retired": safe([f for f in files if f.get("state") == "retired"]),
            "quarantine": safe([f for f in files if f.get("state") in ("quarantined", "banned")]),
            "recovery_holding": safe([f for f in files if f.get("state") == "legacy_externalized"]),
            "metadata": {
                "created_at": section.get("created_at"),
                "description": section.get("description", ""),
                "file_count": len(files),
            },
            "blackbox": self._section_blackbox_summary(project_id, section_id),
            "is_vault_open": self._is_open,
        }

    def get_state(self) -> Dict[str, Any]:
        with self.catalog_snapshot():
            state = copy.deepcopy(self._state)
        return {**state, "is_vault_open": self._is_open}
