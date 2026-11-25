from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet_blackbox import outbox as module
from iteration_wallet_blackbox.models import WalletFact
from iteration_wallet_blackbox.outbox import DurableOutbox, OutboxIntegrityError


def test_outbox_rejects_zero_progress_write(tmp_path: Path, monkeypatch):
    outbox = DurableOutbox(tmp_path / "outbox")
    monkeypatch.setattr(module.os, "write", lambda *_args, **_kwargs: 0)
    with pytest.raises(OutboxIntegrityError, match="no forward progress"):
        outbox.enqueue(WalletFact(operation_id="op-zero", event_type="ZERO_PROGRESS", actor="human:test", object_id="object:test", project_id="project:test"))
