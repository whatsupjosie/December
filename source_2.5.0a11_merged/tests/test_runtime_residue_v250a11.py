from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from iteration_wallet.runtime_residue import RuntimeResidueError, RuntimeResidueRegistry


def _artifact(registry: RuntimeResidueRegistry, name: str = "scratch.bin", content: bytes = b"temporary") -> Path:
    path = registry.class_root("diagnostic_scratch") / name
    path.write_bytes(content)
    return path


def test_registered_runtime_residue_is_cleaned_exactly_and_receipt_remains(tmp_path: Path):
    registry = RuntimeResidueRegistry(tmp_path / "wallet")
    artifact = _artifact(registry)
    registration = registry.register(artifact, residue_class="diagnostic_scratch", transaction_id="tx-1")
    marker = Path(registration["marker"])

    plan = registry.plan()
    assert plan["eligible_count"] == 1
    assert plan["retained_count"] == 0
    result = registry.execute(plan)

    assert result["status"] == "complete"
    assert result["handled_count"] == 1
    assert not artifact.exists()
    assert not marker.exists()
    receipt = Path(result["receipt_path"])
    assert receipt.is_file()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["handled"][0]["sha256"] == registration["sha256"]


def test_outside_root_and_authoritative_reference_are_never_registered(tmp_path: Path):
    registry = RuntimeResidueRegistry(tmp_path / "wallet")
    outside = tmp_path / "protected.txt"
    outside.write_text("protected", encoding="utf-8")
    with pytest.raises(RuntimeResidueError):
        registry.register(outside, residue_class="diagnostic_scratch")

    artifact = _artifact(registry)
    with pytest.raises(RuntimeResidueError, match="authoritative references"):
        registry.register(
            artifact,
            residue_class="diagnostic_scratch",
            authoritative_references=["candidate:abc"],
        )
    assert artifact.is_file()


def test_unregistered_file_is_untouched(tmp_path: Path):
    registry = RuntimeResidueRegistry(tmp_path / "wallet")
    artifact = _artifact(registry, name="unregistered.bin")
    plan = registry.plan()
    assert plan["eligible_count"] == 0
    result = registry.execute(plan)
    assert result["handled_count"] == 0
    assert artifact.read_bytes() == b"temporary"


def test_future_retention_and_changed_content_fail_closed(tmp_path: Path):
    registry = RuntimeResidueRegistry(tmp_path / "wallet")
    future = _artifact(registry, name="future.bin")
    registry.register(future, residue_class="diagnostic_scratch", safe_after=4_000_000_000)
    plan = registry.plan()
    assert plan["eligible_count"] == 0
    assert plan["retained_count"] == 1
    assert future.is_file()

    current = _artifact(registry, name="changed.bin")
    registry.register(current, residue_class="diagnostic_scratch")
    ready = registry.plan()
    assert ready["eligible_count"] == 1
    current.write_bytes(b"changed after planning")
    with pytest.raises(RuntimeResidueError, match="content changed|size changed|changed after planning"):
        registry.execute(ready)
    assert current.is_file()


def test_marker_replaced_after_planning_is_not_deleted(tmp_path: Path):
    registry = RuntimeResidueRegistry(tmp_path / "wallet")
    artifact = _artifact(registry, name="marker-race.bin")
    registration = registry.register(artifact, residue_class="diagnostic_scratch")
    marker = Path(registration["marker"])
    ready = registry.plan()
    replacement = b'{"untrusted":"replacement marker"}'
    marker.write_bytes(replacement)

    with pytest.raises(
        RuntimeResidueError,
        match="schema is invalid|signature is invalid|changed after planning",
    ):
        registry.execute(ready)

    assert artifact.is_file()
    assert marker.read_bytes() == replacement


def test_unlink_exact_rejects_content_outside_pinned_state(tmp_path: Path):
    target = tmp_path / "target.bin"
    target.write_bytes(b"current content")

    with pytest.raises(RuntimeResidueError, match="content changed"):
        RuntimeResidueRegistry._unlink_exact(
            target,
            expected_size=len(b"current content"),
            expected_sha256=hashlib.sha256(b"different bytes").hexdigest(),
        )

    assert target.read_bytes() == b"current content"


def test_forged_marker_symlink_and_hardlink_fail_closed(tmp_path: Path):
    registry = RuntimeResidueRegistry(tmp_path / "wallet")
    artifact = _artifact(registry, name="forged.bin")
    registration = registry.register(artifact, residue_class="diagnostic_scratch")
    marker = Path(registration["marker"])
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["size"] = int(payload["size"]) + 1
    marker.write_text(json.dumps(payload), encoding="utf-8")
    plan = registry.plan()
    assert plan["eligible_count"] == 0
    assert plan["retained_count"] == 1
    assert artifact.is_file()

    target = registry.class_root("diagnostic_scratch") / "target.bin"
    target.write_bytes(b"target")
    link = registry.class_root("diagnostic_scratch") / "link.bin"
    try:
        link.symlink_to(target)
    except OSError:
        pass
    else:
        with pytest.raises(RuntimeResidueError, match="symlink"):
            registry.register(link, residue_class="diagnostic_scratch")

    primary = registry.class_root("diagnostic_scratch") / "primary.bin"
    secondary = registry.class_root("diagnostic_scratch") / "secondary.bin"
    primary.write_bytes(b"hardlink")
    try:
        os.link(primary, secondary)
    except OSError:
        pass
    else:
        with pytest.raises(RuntimeResidueError, match="hard-linked"):
            registry.register(primary, residue_class="diagnostic_scratch")
