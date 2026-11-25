from pathlib import Path


def test_blackbox_core_does_not_import_wallet_or_pubcast():
    root = Path(__file__).resolve().parents[1] / "blackbox_plugin"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "iteration_wallet" not in text
    assert "modules.pubcast" not in text


def test_portable_core_exposes_no_delete_or_execute_api():
    from blackbox_plugin import BlackBoxPlugin

    forbidden = {"delete", "unlink", "execute", "run_target", "promote", "approve"}
    names = set(dir(BlackBoxPlugin))
    assert not names & forbidden
