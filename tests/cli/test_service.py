"""CLI-adapter tests for ``lux service register`` and ``lux service ls``."""

from __future__ import annotations

from typing import Self, final
from unittest.mock import patch

from typer.testing import CliRunner, Result

from punt_lux.cli.__main__ import app
from punt_lux.wire.operations import Ok, OpError, Scope
from punt_lux.wire.operations.service_requests import RegisterServiceRequest
from punt_lux.wire.operations.service_results import ServiceEntry, ServiceList

runner = CliRunner()


@final
class _ServiceClient:
    """A client double: ``client.service.sync`` is a recording ``ServiceOps``."""

    registered: list[RegisterServiceRequest | OpError]
    outcome: Ok | OpError
    listing: ServiceList | OpError
    __slots__ = ("listing", "outcome", "registered")

    def __new__(
        cls,
        outcome: Ok | OpError | None = None,
        listing: ServiceList | OpError | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self.registered = []
        self.outcome = outcome if outcome else Ok()
        self.listing = listing if listing else ServiceList(services=[])
        return self

    @property
    def service(self) -> _ServiceClient:
        return self

    @property
    def sync(self) -> _ServiceClient:
        return self

    def register_service(
        self, request: RegisterServiceRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        del scope
        self.registered.append(request)
        return self.outcome

    def list_services(self, *, scope: Scope) -> ServiceList | OpError:
        del scope
        return self.listing


def _invoke(client: _ServiceClient, *args: str) -> Result:
    with patch("punt_lux.client.facade.LuxClient.for_identity", return_value=client):
        return runner.invoke(app, ["service", *args])


def test_register_sends_the_parsed_service_name() -> None:
    client = _ServiceClient()

    result = _invoke(client, "register", "terminal")

    assert result.exit_code == 0
    assert "registered:terminal" in result.output
    assert client.registered == [RegisterServiceRequest(service="terminal")]


def test_register_of_a_malformed_name_fails_without_reaching_the_hub() -> None:
    client = _ServiceClient()

    result = _invoke(client, "register", "Not A Name")

    assert result.exit_code == 1
    assert "error:" in result.output
    assert client.registered == []


def test_register_shows_the_hubs_refusal() -> None:
    client = _ServiceClient(
        outcome=OpError(code="push_required", reason="no listen leg")
    )

    result = _invoke(client, "register", "terminal")

    assert result.exit_code == 1
    assert "no listen leg" in result.output


def test_ls_prints_one_line_per_registration() -> None:
    client = _ServiceClient(
        listing=ServiceList(services=[ServiceEntry(service="terminal", host="okinos")])
    )

    result = _invoke(client, "ls")

    assert result.exit_code == 0
    assert "terminal okinos" in result.output


def test_ls_json_carries_the_listing() -> None:
    client = _ServiceClient(
        listing=ServiceList(services=[ServiceEntry(service="terminal", host="okinos")])
    )

    result = _invoke(client, "ls", "--json")

    assert result.exit_code == 0
    assert '"service": "terminal"' in result.output
