from __future__ import annotations

import json
from pathlib import Path

from blackbox_plugin.cli import main


def _run(capsys, argv):
    code = main(argv)
    output = capsys.readouterr().out
    return code, json.loads(output)


def test_standalone_cli_capabilities_status_and_receipt(tmp_path: Path, capsys):
    storage = str(tmp_path / "bbx")
    session = "standalone"
    code, capabilities = _run(capsys, ["capabilities", "--storage", storage, "--session", session])
    assert code == 0
    assert capabilities["schema_version"] == "bbx1-client/1"
    assert capabilities["direct_storage_access"] is False

    code = main([
        "record", "--storage", storage, "--session", session,
        "--event-type", "candidate.observed", "--source", "cli-test",
        "--actor", "human:owner", "--subject", "object:one",
        "--operation-id", "operation:one", "--payload", '{"state":"candidate"}',
    ])
    receipt = json.loads(capsys.readouterr().out)
    assert code == 0

    code, status = _run(capsys, ["status", "--storage", storage, "--session", session])
    assert code == 0
    assert status["verification"]["ok"] is True
    assert status["health"]["sequence"] == 1

    code, verified = _run(capsys, [
        "verify-receipt", "--storage", storage, "--session", session,
        "--record-id", receipt["record_id"], "--event-hash", receipt["event_hash"],
        "--sequence", str(receipt["sequence"]),
    ])
    assert code == 0
    assert verified["ok"] is True
