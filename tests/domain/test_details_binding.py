"""DetailsBinding — how a Details click reaches the operation that answers it.

The dispatch is domain code and may not call the operations layer, so the
composition root binds the renderer. Before it does, the binding holds the Null
Object: the click is logged and nothing else happens.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.details_binding import (
    ClientDetailsRenderer,
    DetailsBinding,
    NoDetailsRenderer,
)
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    import pytest


@final
class _Renderer:
    """A renderer recording the connections it was asked about."""

    _asked: list[ConnectionId]
    __slots__ = ("_asked",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._asked = []
        return self

    def show_client_details(self, connection_id: ConnectionId) -> object:
        self._asked.append(connection_id)
        return None

    @property
    def asked(self) -> tuple[ConnectionId, ...]:
        return tuple(self._asked)


def test_a_bound_renderer_answers_the_command() -> None:
    binding, renderer = DetailsBinding(), _Renderer()
    binding.bind(renderer)

    binding.run(ConnectionId("c1"))

    assert renderer.asked == (ConnectionId("c1"),)


def test_the_last_binding_wins() -> None:
    """luxd composes a facade for MCP and another for REST; either may answer."""
    binding, first, second = DetailsBinding(), _Renderer(), _Renderer()
    binding.bind(first)
    binding.bind(second)

    binding.run(ConnectionId("c1"))

    assert first.asked == ()
    assert second.asked == (ConnectionId("c1"),)


def test_an_unbound_binding_says_so_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A click before luxd finished composing itself is reported, never fatal."""
    with caplog.at_level(logging.WARNING):
        DetailsBinding().run(ConnectionId("c1"))

    assert "before luxd bound its renderer" in caplog.text


def test_the_null_object_satisfies_the_renderer_contract() -> None:
    assert isinstance(NoDetailsRenderer(), ClientDetailsRenderer)


def test_a_real_renderer_satisfies_the_renderer_contract() -> None:
    assert isinstance(_Renderer(), ClientDetailsRenderer)
