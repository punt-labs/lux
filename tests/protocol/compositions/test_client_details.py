"""ClientDetails.rows() -- the lines a person reads one client's state as."""

from __future__ import annotations

from punt_lux.domain.hub.lease_term import LeaseTerms
from punt_lux.protocol.compositions.client_details import ClientDetails


def _details(**overrides: object) -> ClientDetails:
    fields: dict[str, object] = {
        "label": "lux",
        "connection_id": "c1",
        "kind": "cli",
        "name": "lux",
        "connected_seconds": 5.0,
        "lease": LeaseTerms.of(60.0),
    }
    fields.update(overrides)
    return ClientDetails.model_validate(fields)


def _row(details: ClientDetails, field: str) -> str:
    return dict(details.rows())[field]


def test_the_host_rows_sit_directly_after_the_connection_row() -> None:
    labels = [label for label, _ in _details().rows()]

    at = labels.index("Connection")

    assert labels[at + 1 : at + 3] == ["Client host", "Hub host"]


def test_an_observed_host_is_reported_as_the_socket_gave_it() -> None:
    assert _row(_details(client_hosts=("::1",)), "Client host") == "::1"


def test_several_hosts_are_comma_joined_in_first_seen_order() -> None:
    details = _details(client_hosts=("10.0.0.5", "127.0.0.1"))

    assert _row(details, "Client host") == "10.0.0.5, 127.0.0.1"


def test_no_observed_host_reads_unknown_not_none_and_not_loopback() -> None:
    value = _row(_details(), "Client host")

    assert value == "unknown"
    assert value not in {"none", "127.0.0.1"}


def test_the_hub_host_is_reported_when_known() -> None:
    assert _row(_details(hub_host="pembroke.example"), "Hub host") == (
        "pembroke.example"
    )


def test_an_unreported_hub_host_reads_unknown() -> None:
    assert _row(_details(), "Hub host") == "unknown"
