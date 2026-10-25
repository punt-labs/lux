"""InteractionHandlers -- who answers a display interaction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    import pytest


def _click(
    element_id: str = "b1", action: str = "click"
) -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(element_id=element_id, action=action)


class TestTheHandler:
    def test_an_interaction_goes_to_the_handler(self) -> None:
        handlers = InteractionHandlers()
        seen: list[str] = []
        handlers.set_fallback(lambda m: seen.append(m.element_id))

        handlers.run(_click("nobody"))

        assert seen == ["nobody"]

    def test_the_latest_handler_answers(self) -> None:
        handlers = InteractionHandlers()
        seen: list[str] = []
        handlers.set_fallback(lambda _m: seen.append("first"))
        handlers.set_fallback(lambda _m: seen.append("second"))

        handlers.run(_click())

        assert seen == ["second"]

    def test_an_interaction_with_no_handler_is_dropped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            InteractionHandlers().run(_click("nobody"))

        assert "Dropping interaction with no handler: nobody:click" in caplog.text

    def test_a_raising_handler_is_logged_and_does_not_escape(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handlers = InteractionHandlers()

        def boom(_m: RemoteEventHandlerInvocation) -> None:
            raise ValueError("handler failed")

        handlers.set_fallback(boom)

        with caplog.at_level(logging.ERROR):
            handlers.run(_click())

        assert "Fallback handler error for b1:click" in caplog.text

    def test_the_error_log_names_the_scene_and_the_hub_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Two scenes can hold the same element id; only the scene (or, for a menu
        # event, the Hub token) says which one a failed click belonged to.
        handlers = InteractionHandlers()

        def boom(_m: RemoteEventHandlerInvocation) -> None:
            raise ValueError("handler failed")

        handlers.set_fallback(boom)
        event = RemoteEventHandlerInvocation(
            element_id="b1", action="click", scene_id="scene-9", hub_token="token-7"
        )

        with caplog.at_level(logging.ERROR):
            handlers.run(event)

        assert "scene-9" in caplog.text
        assert "token-7" in caplog.text
