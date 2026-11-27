"""LocalHost — the machine name every default-host identity declares."""

from __future__ import annotations

import socket

import pytest

from punt_lux.kernel.local_host import LocalHost
from punt_lux.wire.model.client_identity import ClientIdentity


def test_name_is_the_machine_name() -> None:
    assert LocalHost.name() == (socket.gethostname().strip() or "localhost")


def test_an_identity_that_names_no_host_declares_this_one() -> None:
    assert ClientIdentity(kind="cli", name="lux-cli").host == LocalHost.name()


@pytest.mark.parametrize("host", ["", "   ", "a\x00b"])
def test_a_blank_or_nul_host_is_rejected(host: str) -> None:
    with pytest.raises(ValueError, match=r"host|NUL"):
        ClientIdentity(kind="cli", name="lux-cli", host=host)
