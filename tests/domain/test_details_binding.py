"""DetailsBinding — how a Details click reaches the operation that answers it.

The dispatch is domain code and may not call the operations layer, so the
composition root binds the renderer. Before it does, the binding holds the Null
Object: the click is logged and nothing else happens.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.details_binding import DetailsBinding
from punt_lux.domain.hub.details_outcome import DetailsRefused, DetailsShown
from punt_lux.domain.hub.details_renderer import (
    ClientDetailsRenderer,
    NoDetailsRenderer,
)
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    import pytest

    from punt_lux.domain.hub.details_outcome import DetailsOutcome


@final
class _Renderer:
    """A renderer recording the connections it was asked about."""

    _asked: list[ConnectionId]
    _refuses: bool
    __slots__ = ("_asked", "_refuses")

    def __new__(cls, *, refuses: bool = False) -> Self:
        self = super().__new__(cls)
        self._asked = []
        self._refuses = refuses
        return self

    def render_details(self, connection_id: ConnectionId) -> DetailsOutcome:
        self._asked.append(connection_id)
        if self._refuses:
            return DetailsRefused(connection_id)
        return DetailsShown()

    @property
    def asked(self) -> tuple[ConnectionId, ...]:
        return tuple(self._asked)


def test_a_bound_renderer_answers_the_command() -> None:
    binding, renderer = DetailsBinding(), _Renderer()
    binding.bind(renderer)

    binding.run(ConnectionId("c1"))

    assert renderer.asked == (ConnectionId("c1"),)


def test_the_last_binding_wins() -> None:
    """luxd builds a renderer at the MCP root and another at REST; either answers."""
    binding, first, second = DetailsBinding(), _Renderer(), _Renderer()
    binding.bind(first)
    binding.bind(second)

    binding.run(ConnectionId("c1"))

    assert first.asked == ()
    assert second.asked == (ConnectionId("c1"),)


def test_a_refused_click_leaves_a_line_naming_the_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A click that outlived its client did nothing; it must not do so silently."""
    binding = DetailsBinding()
    binding.bind(_Renderer(refuses=True))

    with caplog.at_level(logging.INFO):
        binding.run(ConnectionId("gone"))

    assert "gone" in caplog.text
    assert "no longer holds a session for" in caplog.text


def test_a_shown_click_leaves_no_refusal_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    binding = DetailsBinding()
    binding.bind(_Renderer())

    with caplog.at_level(logging.INFO):
        binding.run(ConnectionId("c1"))

    assert "no longer holds a session for" not in caplog.text


def test_an_unbound_binding_says_so_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A click before luxd finished composing itself is reported, never fatal."""
    with caplog.at_level(logging.WARNING):
        DetailsBinding().run(ConnectionId("c1"))

    assert "before luxd bound its renderer" in caplog.text


def test_an_unbound_click_leaves_one_line_and_does_not_blame_the_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nothing asked whether the Hub holds that session, so nothing may say it did.

    Two lines for one click is two explanations, and the second one here would
    be a reason that was never checked.
    """
    with caplog.at_level(logging.DEBUG):
        DetailsBinding().run(ConnectionId("c1"))

    assert len(caplog.records) == 1
    assert "no longer holds a session for" not in caplog.text


def test_the_null_object_satisfies_the_renderer_contract() -> None:
    assert isinstance(NoDetailsRenderer(), ClientDetailsRenderer)


def test_a_real_renderer_satisfies_the_renderer_contract() -> None:
    assert isinstance(_Renderer(), ClientDetailsRenderer)
