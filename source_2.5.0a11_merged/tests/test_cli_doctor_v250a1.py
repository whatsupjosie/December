from __future__ import annotations

from iteration_wallet.cli import _doctor_report


def test_doctor_requires_one_owner_per_product_package():
    good = _doctor_report(ownership={
        "blackbox_plugin": ["bbx1-iteration-wallet-plugin"],
        "iteration_wallet_blackbox": ["iteration-wallet"],
    })
    assert good["checks"]["blackbox_single_owner"] is True
    assert good["checks"]["wallet_adapter_single_owner"] is True
    assert good["checks"]["no_shared_package_owner"] is True

    duplicate = _doctor_report(ownership={
        "blackbox_plugin": ["bbx1-iteration-wallet-plugin", "iteration-wallet"],
        "iteration_wallet_blackbox": ["iteration-wallet"],
    })
    assert duplicate["ok"] is False
    assert duplicate["checks"]["blackbox_single_owner"] is False
    assert duplicate["checks"]["no_shared_package_owner"] is False


def test_package_root_keeps_version_available_without_loading_runtime_exports():
    import iteration_wallet
    from iteration_wallet.version import WALLET_VERSION

    assert iteration_wallet.__version__ == WALLET_VERSION
    assert "NotificationManager" in dir(iteration_wallet)


def test_doctor_report_contains_explicit_legacy_migration_guidance():
    report = _doctor_report(ownership={
        "blackbox_plugin": ["iteration-wallet", "bbx1-iteration-wallet-plugin"],
        "iteration_wallet_blackbox": ["bbx1-iteration-wallet-plugin"],
    })
    assert report["ok"] is False
    assert "shared package ownership" in report["repair"]["reason"]
    assert "migrate_alpha_install.py" in report["repair"]["safe_method"]
