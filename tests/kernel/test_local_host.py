"""LocalHost — the machine name every default-host identity declares."""

from __future__ import annotations

import pytest

from punt_lux.kernel.local_host import LocalHost
from punt_lux.wire.model.client_identity import ClientIdentity


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("okinos", "okinos"),
        ("  okinos \n", "okinos"),
        ("", "localhost"),
        ("   ", "localhost"),
        ("bad\nname", "localhost"),
        ("bad\x00name", "localhost"),
        ("bad\x1bname", "localhost"),
    ],
)
def test_a_reported_name_is_stripped_and_a_blank_one_is_localhost(
    reported: str, expected: str
) -> None:
    assert LocalHost.named(reported) == expected


def test_the_machine_name_is_a_real_label_read_once() -> None:
    name = LocalHost.name()
    assert name == name.strip() != ""
    assert LocalHost.name() is name


def test_an_identity_that_names_no_host_declares_this_one() -> None:
    assert ClientIdentity(kind="cli", name="lux-cli").host == LocalHost.name()


@pytest.mark.parametrize("host", ["", "   ", "a\x00b"])
def test_a_blank_or_nul_host_is_rejected(host: str) -> None:
    with pytest.raises(ValueError, match=r"host|NUL"):
        ClientIdentity(kind="cli", name="lux-cli", host=host)


@pytest.mark.parametrize("peer", ["127.0.0.1", "127.0.0.2", "::1"])
def test_a_loopback_peer_is_this_machine(peer: str) -> None:
    assert LocalHost.canonical(peer) == LocalHost.name()


@pytest.mark.parametrize(
    "host", ["okinos", "10.0.0.9", "192.168.1.5", "localhost", "127.lab"]
)
def test_any_other_host_is_itself(host: str) -> None:
    assert LocalHost.canonical(host) == host
