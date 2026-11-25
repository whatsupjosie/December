from pathlib import Path

from tools.oubliette_boundary_demo import run_demo


def test_bounded_oubliette_demo_proves_preservation_and_candidate_only_return(tmp_path: Path):
    report = run_demo(tmp_path / "demo")
    assert report["ok"] is True
    from iteration_wallet.version import WALLET_VERSION
    assert report["version"] == WALLET_VERSION
    assert all(report["assertions"].values())
    assert report["original_object_id"] != report["derivative_candidate_id"]
