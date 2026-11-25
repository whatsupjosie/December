"""Test-only environment controls.

The shipped product requires passkey enrollment before protected operations.
Most regression tests exercise lower-level custody and evidence contracts and
therefore use an explicit test-only override. Passkey tests opt back into the
required policy themselves.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _explicit_test_only_passkey_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "off")
