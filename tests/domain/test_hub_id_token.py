"""HubIdToken -- resolving a ConnectMessage.hub_id wire string into a HubId."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.hub_id import HubId
from punt_lux.domain.hub.hub_id_token import HubIdToken


def test_resolve_round_trips_a_real_hub_ids_wire_token() -> None:
    hub_id = HubId("pembroke", 123)
    assert HubIdToken(hub_id.wire_token).resolve() == hub_id


def test_resolve_round_trips_current() -> None:
    hub_id = HubId.current()
    assert HubIdToken(hub_id.wire_token).resolve() == hub_id


def test_resolve_round_trips_stub() -> None:
    hub_id = HubId.stub()
    assert HubIdToken(hub_id.wire_token).resolve() == hub_id


def test_resolve_rejects_a_token_with_no_separator() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("pembroke123").resolve()


def test_resolve_rejects_a_blank_hostname() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("\x1f123").resolve()


def test_resolve_rejects_a_non_numeric_pid() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("pembroke\x1fabc").resolve()


def test_resolve_rejects_an_empty_string() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("").resolve()
