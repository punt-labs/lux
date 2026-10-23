"""Hub.hostname -- the Hub's own host, resolved once and on demand."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub_id import HubId

if TYPE_CHECKING:
    import pytest


def test_is_the_hostname_the_hub_declares_to_a_display() -> None:
    assert Hub().hostname == HubId.current().hostname


def test_is_not_resolved_when_the_hub_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[None] = []

    def counting_fqdn(*_args: object) -> str:
        calls.append(None)
        return "pembroke.example"

    monkeypatch.setattr(socket, "getfqdn", counting_fqdn)

    Hub()

    assert calls == []


def test_is_resolved_once_however_often_it_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[None] = []

    def counting_fqdn(*_args: object) -> str:
        calls.append(None)
        return "Pembroke.Example"

    monkeypatch.setattr(socket, "getfqdn", counting_fqdn)
    hub = Hub()

    first, second, third = hub.hostname, hub.hostname, hub.hostname

    assert (first, second, third) == ("pembroke.example",) * 3
    assert len(calls) == 1


def test_each_hub_resolves_its_own() -> None:
    assert Hub().hostname == Hub().hostname
