from __future__ import annotations

import json
from pathlib import Path

import pytest

from blackbox_plugin import (
    BlackBoxPlugin,
    Coverage,
    EvidenceEvent,
    ObservationMode,
    RecorderIntegrityError,
    RecorderSealedError,
)
from blackbox_plugin.discovery import closed_discovery_summary, discover_ai_profiles
from blackbox_plugin.recorder import SegmentedBlackBoxRecorder, verify_session
from blackbox_plugin.sentinel import IntegritySentinel


def event(session: str, n: int, *, operation_id: str | None = None, subject: str = "object:1", payload=None):
    return EvidenceEvent(
        event_type="candidate.observed",
        source="iteration_wallet",
        actor="human:owner",
        subject_id=subject,
        session_id=session,
        operation_id=operation_id,
        source_sequence=n,
        observation_mode=ObservationMode.DIRECT,
        coverage=Coverage.FULL,
        payload=payload or {"state": "candidate", "path": "/protected/item", "token_secret": "never-show"},
        channel="CUS",
        event_code="VER",
    )


def test_standalone_append_verify_seal_and_closed_summary(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "session-a", checkpoint_every_events=2, max_records_per_segment=2)
    plugin.append_event(event("session-a", 1, operation_id="op-1"))
    plugin.append_event(event("session-a", 2, operation_id="op-2"))
    plugin.append_event(event("session-a", 3, operation_id="op-3"))
    assert plugin.verify()["ok"] is True
    assert plugin.verify()["segment_count"] == 2
    summary = plugin.closed_summary()
    assert summary["chain_verified"] is True
    assert summary["protected_values_exposed"] is False
    plugin.seal("test")
    assert plugin.verify()["sealed"] is True
    with pytest.raises(RecorderSealedError):
        plugin.append_event(event("session-a", 4, operation_id="op-4"))


def test_record_hash_tampering_is_detected(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "tamper")
    plugin.append_event(event("tamper", 1))
    segment = next((plugin.session_dir / "segments").glob("*.bbx"))
    raw = bytearray(segment.read_bytes())
    raw[len(raw) // 2] ^= 1
    segment.write_bytes(bytes(raw))
    result = verify_session(plugin.session_dir)
    assert result.ok is False
    assert result.errors


def test_missing_segment_and_seal_reorder_are_detected(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "segments", max_records_per_segment=1)
    for n in range(1, 5):
        plugin.append_event(event("segments", n, operation_id=f"op-{n}"))
    plugin.seal("segment proof")
    seal = json.loads((plugin.session_dir / "seal.json").read_text(encoding="utf-8"))
    seal["segments"] = list(reversed(seal["segments"]))
    (plugin.session_dir / "seal.json").write_text(json.dumps(seal), encoding="utf-8")
    assert verify_session(plugin.session_dir).ok is False


def test_source_sequence_replay_is_visible(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "source-seq")
    plugin.append_event(event("source-seq", 4, operation_id="a"))
    plugin.append_event(event("source-seq", 4, operation_id="b"))
    result = plugin.verify()
    assert result["ok"] is False
    assert any("source sequence replay" in error for error in result["errors"])


def test_crash_tail_is_preserved_recovered_and_sealable(tmp_path: Path):
    root = tmp_path / "bbx"
    first = BlackBoxPlugin(root, "crash", max_records_per_segment=10)
    first.append_event(event("crash", 1, operation_id="before"))
    segment = next((first.session_dir / "segments").glob("*.bbx"))
    with segment.open("ab") as handle:
        handle.write(b"BBX1|partial-tail")
    recovered = BlackBoxPlugin(root, "crash", max_records_per_segment=10)
    assert (recovered.session_dir / "recovery.json").exists()
    recovered.append_event(event("crash", 2, operation_id="after"))
    result = recovered.verify()
    assert result["ok"] is True
    assert result["recoverable_tail"] is True
    recovered.seal("recovered crash tail")
    assert recovered.verify()["ok"] is True


def test_operation_retries_are_idempotent_and_conflicts_fail(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "idempotent")
    original = event("idempotent", 1, operation_id="same-op", payload={"state": "candidate"})
    first = plugin.append_event(original)
    retry = plugin.append_event(original)
    assert retry.duplicate is True
    assert retry.record_id == first.record_id
    conflicting = event("idempotent", 1, operation_id="same-op", payload={"state": "prime"})
    with pytest.raises(RecorderIntegrityError):
        plugin.append_event(conflicting)


def test_contextual_history_is_derived_and_redacted(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "history")
    plugin.append_event(event("history", 1, subject="file:77"))
    history = plugin.object_history("file:77")
    assert history["derived_from_canonical_blackbox"] is True
    assert history["authoritative"] is False
    assert history["protected_values_exposed"] is False
    payload = history["history"][0]["payload"]
    assert "path" not in payload
    assert "token_secret" not in payload
    assert payload["state"] == "candidate"


def test_local_reference_comparator_requires_human_and_never_repairs(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "app.py").write_text("print('known')\n", encoding="utf-8")
    manifest = tmp_path / "reference" / "golden.json"
    sentinel = IntegritySentinel()
    with pytest.raises(PermissionError):
        sentinel.commission_reference(target, manifest, actor_id="ai:builder", human_authorized=True)
    sentinel.commission_reference(target, manifest, actor_id="human:owner", human_authorized=True)
    verified = sentinel.verify_target(target, manifest)
    assert verified["ok"] is True
    assert verified["independently_authenticated"] is False
    assert verified["authentication_scope"] == "local_consistency_only"
    (target / "app.py").write_text("print('changed')\n", encoding="utf-8")
    result = sentinel.verify_target(target, manifest)
    assert result["ok"] is False
    assert result["counts"]["changed"] == 1
    assert result["repair_attempted"] is False
    assert result["active_target_self_certified"] is False


def test_ai_discovery_is_config_bounded_and_non_networked(tmp_path: Path):
    config = tmp_path / "ai_runtime.json"
    config.write_text(json.dumps({"profiles": {"local": {"backend": "ollama", "model": "gemma3:1b", "endpoint": "http://127.0.0.1:11434", "enabled": True}}}), encoding="utf-8")
    profiles = discover_ai_profiles([config])
    summary = closed_discovery_summary(profiles)
    assert summary["profile_count"] == 1
    assert summary["network_probed"] is False
    assert summary["system_wide_scan_performed"] is False
    assert summary["human_approval_required_before_binding"] is True



