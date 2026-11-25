from datetime import datetime, timedelta
from pathlib import Path

import pytest

from iteration_wallet.notification_manager import (
    ActorKind,
    ApprovalRequest,
    NotificationLevel,
    NotificationManager,
    RequestClassification,
    RequestStatus,
)


def test_approval_request_expiration_exists_and_works():
    approval = ApprovalRequest(
        vault_id="v1",
        object_id="obj",
        action="export_working_copy",
        requester_id="bot-a",
        claimed_purpose="compare against Prime",
        head_user_id="josie",
    )
    approval.expires_at = datetime.now() - timedelta(seconds=1)
    assert approval.is_expired() is True


def test_message_length_limit_rejects_long_alert(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    note = nm.create_notification("josie", "x" * 151, NotificationLevel.INFO)
    assert note is None
    assert nm.get_notification_status()["total_notifications"] == 0


def test_per_recipient_limit_is_five_unread_messages(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    for i in range(10):
        nm.create_notification("josie", f"msg {i}", NotificationLevel.INFO)
    inbox = nm.get_inbox("josie")
    assert len(inbox) == 5
    assert all(len(n["message"]) <= 150 for n in inbox)


def test_system_limit_is_two_hundred_messages(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    # 40 recipients * 5 unread messages = 200 exactly.
    for r in range(50):
        for i in range(5):
            nm.create_notification(f"user-{r}", f"msg {r}-{i}", NotificationLevel.INFO)
    status = nm.get_notification_status()
    assert status["total_notifications"] == 200
    assert status["capacity_remaining"] == 0
    assert nm.create_notification("extra", "should not send", NotificationLevel.INFO) is None


def test_head_user_approval_decision_updates_status_and_notifies_requester(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    approval = nm.create_approval_request(
        vault_id="vault",
        object_id="candidate-04",
        action="export working copy",
        requester_id="codex-agent",
        claimed_purpose="compare against Prime",
        head_user_id="head-user",
    )
    head_session = nm.issue_identity_session(
        "head-user",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony"],
    )
    decided = nm.submit_approval_decision(
        approval.approval_id,
        approved=False,
        decision_session_id=head_session.session_id,
        reason="not now",
    )
    assert decided is not None
    assert decided.status == RequestStatus.DENIED
    assert decided.decision_by == "head-user"
    assert any("denied" in n["message"] for n in nm.get_inbox("codex-agent"))


@pytest.mark.parametrize(
    "count,classification",
    [
        (1, RequestClassification.NORMAL),
        (20, RequestClassification.UNUSUAL_PRESSURE),
        (50, RequestClassification.SUSPICIOUS_PATTERN),
        (100, RequestClassification.PROBABLE_INTRUSION),
        (1000, RequestClassification.ACTIVE_FLOOD),
    ],
)
def test_request_threshold_classification(tmp_path: Path, count, classification):
    nm = NotificationManager(tmp_path)
    assert nm.classify_request_pressure(count) == classification


def test_bot_cannot_directly_access_protected_custody(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    denied = nm.evaluate_direct_access(ActorKind.AI_ASSISTANT, "fetch protected file", protected=True)
    assert denied["allowed"] is False
    assert "No autonomous bot" in denied["reason"]
    allowed = nm.evaluate_direct_access(ActorKind.HUMAN, "open cradle", protected=True, human_ceremony_passed=True)
    assert allowed["allowed"] is True


def test_access_request_logs_blackbox_and_sends_capped_alerts(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    req = nm.create_access_request(
        vault_id="vault",
        object_id="candidate-04-super-long-id",
        action="export working copy",
        requester_id="ai-agent-1",
        requester_kind=ActorKind.AI_ASSISTANT,
        claimed_purpose="compare against Prime",
        recipients=["head-user"],
        head_user_id="head-user",
        tool_family="ai-family",
    )
    assert req.request_id
    assert req.status in {RequestStatus.NOTIFIED, RequestStatus.PENDING_APPROVAL}
    inbox = nm.get_inbox("head-user")
    assert 1 <= len(inbox) <= 5
    assert all(len(n["message"]) <= 150 for n in inbox)
    assert (nm.request_dir / f"{req.request_id}.json").exists()
    assert nm.blackbox.records()


def test_repeated_bot_requests_become_possible_intrusion_evidence(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    last = None
    for i in range(100):
        last = nm.create_access_request(
            vault_id="vault",
            object_id="prime",
            action="open cradle",
            requester_id="bot-pressure",
            requester_kind=ActorKind.BOT,
            claimed_purpose="fetch",
            recipients=["head-user"],
            head_user_id="head-user",
            tool_family="botnet-ish",
        )
    assert last is not None
    assert last.matching_request_count >= 100
    assert last.classification == RequestClassification.PROBABLE_INTRUSION
    assert last.status == RequestStatus.FROZEN
    report = nm.build_blackbox_request_report(limit=200)
    assert report["possible_intrusion_records"]
    assert report["counts_by_requester"]["bot-pressure"] == 100
    # User is not spammed beyond five unread messages.
    assert len(nm.get_inbox("head-user")) == 5



def test_request_report_surfaces_corrupt_incident_coverage(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    nm.incident_dir.mkdir(parents=True, exist_ok=True)
    (nm.incident_dir / "broken-incident.json").write_text(
        '{"incident_id":',
        encoding="utf-8",
    )

    report = nm.build_blackbox_request_report()

    assert report["incident_coverage"] == "partial"
    assert report["incident_bundles"] == []
    assert report["incident_read_errors"]
    assert report["incident_read_errors"][0]["file"] == "broken-incident.json"
    assert "unreadable incident bundle" in report["incident_read_errors"][0]["error"]

def test_flood_threshold_causes_emergency_lockout_with_small_config(tmp_path: Path):
    # Use a strict config so the 1000-request behavior can be tested quickly.
    (tmp_path / "notification_limits.json").write_text(
        '{"warning_threshold": 2, "suspicious_threshold": 3, "intrusion_threshold": 4, "flood_threshold": 5}',
        encoding="utf-8",
    )
    nm = NotificationManager(tmp_path)
    last = None
    for _ in range(5):
        last = nm.create_access_request(
            vault_id="vault",
            object_id="prime",
            action="open cradle",
            requester_id="flood-bot",
            requester_kind=ActorKind.BOT,
            claimed_purpose="break in",
            recipients=["head-user"],
            head_user_id="head-user",
        )
    assert last.classification == RequestClassification.ACTIVE_FLOOD
    assert last.status == RequestStatus.EMERGENCY_LOCKOUT
    assert "hostile" in last.system_action
