from pathlib import Path
import json
import pytest

from iteration_wallet.notification_manager import (
    ActorKind,
    NotificationError,
    NotificationLevel,
    NotificationManager,
    RequestClassification,
    RequestStatus,
)


def test_head_user_or_admin_required_for_approval_decision(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    nm.configure_vault_roles("vault", head_user_id="head", admins=["admin-a"])
    approval = nm.create_approval_request("vault", "prime", "export working copy", "bot", "compare", "head")

    with pytest.raises(NotificationError):
        nm.submit_approval_decision(approval.approval_id, True, decision_by="random-user")

    admin_session = nm.issue_identity_session(
        "admin-a",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony"],
    )
    approved = nm.submit_approval_decision(
        approval.approval_id,
        True,
        decision_session_id=admin_session.session_id,
    )
    assert approved.status == RequestStatus.APPROVED
    assert approved.decision_by == "admin-a"


def test_request_count_uses_time_window(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    first = nm.create_access_request("vault", "prime", "open cradle", "bot", "fetch", ActorKind.BOT, ["head"], "head")
    # Move first request outside the rolling one-hour window.
    path = nm.request_dir / f"{first.request_id}.json"
    data = json.loads(path.read_text())
    data["created_at"] = "2000-01-01T00:00:00"
    path.write_text(json.dumps(data), encoding="utf-8")

    second = nm.create_access_request("vault", "prime", "open cradle", "bot", "fetch", ActorKind.BOT, ["head"], "head")
    assert second.matching_request_count == 1
    assert second.classification == RequestClassification.NORMAL


def test_repeated_requests_collapse_into_incident_bundle(tmp_path: Path):
    (tmp_path / "notification_limits.json").write_text(
        '{"warning_threshold": 3, "suspicious_threshold": 4, "intrusion_threshold": 5, "flood_threshold": 10}',
        encoding="utf-8",
    )
    nm = NotificationManager(tmp_path)
    last = None
    for _ in range(4):
        last = nm.create_access_request("vault", "prime", "open cradle", "bot", "fetch", ActorKind.BOT, ["head"], "head")
    assert last.status == RequestStatus.FROZEN
    incidents = list(nm.incident_dir.glob("*.json"))
    assert incidents
    incident = json.loads(incidents[0].read_text())
    assert incident["matching_request_count"] >= 3
    assert "raw_request_ids" in incident
    # Collapsed requests do not create unlimited normal approval objects.
    approvals = list((tmp_path / "approvals").glob("*.json"))
    assert len(approvals) < 4


def test_intrusion_alert_can_displace_low_priority_unread_messages(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    for i in range(5):
        assert nm.create_notification("head", f"low {i}", NotificationLevel.INFO)
    assert len(nm.get_inbox("head")) == 5
    high = nm.create_notification("head", "Possible hacking attempt detected.", NotificationLevel.INTRUSION)
    assert high is not None
    inbox = nm.get_inbox("head")
    assert len(inbox) == 5
    assert any(n["level"] == "intrusion" for n in inbox)


def test_blackbox_events_are_hash_chained_and_tamper_visible(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    nm.create_access_request("vault", "prime", "open cradle", "bot", "fetch", ActorKind.BOT, ["head"], "head")
    result = nm.verify_blackbox_chain()
    assert result["ok"] is True

    segment = next(nm.event_dir.glob("*.bbx"))
    material = bytearray(segment.read_bytes())
    material[len(material) // 2] ^= 0x01
    segment.write_bytes(bytes(material))
    result = nm.verify_blackbox_chain()
    assert result["ok"] is False
