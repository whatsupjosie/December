from __future__ import annotations

import pytest

from iteration_wallet.network_policy import NetworkPolicyError, require_loopback_host


def test_supported_loopback_hosts_are_normalized():
    assert require_loopback_host("localhost") == ("127.0.0.1", "localhost")
    assert require_loopback_host("127.0.0.1") == ("127.0.0.1", "localhost")
    assert require_loopback_host("::1") == ("::1", "[::1]")


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "example.test", "8.8.8.8"])
def test_non_loopback_binding_is_refused(host: str):
    with pytest.raises(NetworkPolicyError):
        require_loopback_host(host)
