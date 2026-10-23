"""InteractionHandlers -- who answers a display interaction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.callback_key import CallbackKey
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    import pytest


def _click(
    element_id: str = "b1", action: str = "click"
) -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(element_id=element_id, action=action)


class TestCallbacks:
    def test_a_registered_callback_receives_its_interaction(self) -> None:
        handlers = InteractionHandlers()
        seen: list[RemoteEventHandlerInvocation] = []
        handlers.register(CallbackKey("b1", "click"), seen.append)

        handlers.run(_click())

        assert [m.element_id for m in seen] == ["b1"]

    def test_only_the_matching_callback_runs(self) -> None:
        handlers = InteractionHandlers()
        seen: list[str] = []
        handlers.register(CallbackKey("b1", "click"), lambda _m: seen.append("b1"))
        handlers.register(CallbackKey("b2", "click"), lambda _m: seen.append("b2"))

        handlers.run(_click("b2"))

        assert seen == ["b2"]

    def test_an_action_mismatch_on_the_same_element_is_dropped(self) -> None:
        handlers = InteractionHandlers()
        seen: list[str] = []
        handlers.register(CallbackKey("b1", "click"), lambda _m: seen.append("ran"))

        handlers.run(_click("b1", "changed"))

        assert seen == []

    def test_a_removed_callback_no_longer_runs(self) -> None:
        handlers = InteractionHandlers()
        seen: list[str] = []
        key = CallbackKey("b1", "click")
        handlers.register(key, lambda _m: seen.append("ran"))
        handlers.remove(key)

        handlers.run(_click())

        assert seen == []

    def test_removing_a_callback_never_registered_is_not_an_error(self) -> None:
        InteractionHandlers().remove(CallbackKey("ghost", "click"))

    def test_a_raising_callback_is_logged_and_the_event_consumed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handlers = InteractionHandlers()

        def boom(_m: RemoteEventHandlerInvocation) -> None:
            raise ValueError("handler failed")

        handlers.register(CallbackKey("b1", "click"), boom)

        with caplog.at_level(logging.ERROR):
            handlers.run(_click())

        assert "Callback error for b1:click" in caplog.text

    def test_any_registered_follows_registration(self) -> None:
        handlers = InteractionHandlers()
        key = CallbackKey("b1", "click")
        states = [handlers.any_registered]
        handlers.register(key, lambda _m: None)
        states.append(handlers.any_registered)
        handlers.remove(key)
        states.append(handlers.any_registered)

        assert states == [False, True, False]


class TestFallback:
    def test_an_unmatched_interaction_goes_to_the_fallback(self) -> None:
        handlers = InteractionHandlers()
        fallen: list[str] = []
        handlers.set_fallback(lambda m: fallen.append(m.element_id))

        handlers.run(_click("nobody"))

        assert fallen == ["nobody"]

    def test_a_matched_interaction_skips_the_fallback(self) -> None:
        handlers = InteractionHandlers()
        fallen: list[str] = []
        handlers.set_fallback(lambda m: fallen.append(m.element_id))
        handlers.register(CallbackKey("b1", "click"), lambda _m: None)

        handlers.run(_click())

        assert fallen == []

    def test_an_unmatched_interaction_with_no_fallback_is_dropped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            InteractionHandlers().run(_click("nobody"))

        assert "Dropping interaction with no callback: nobody:click" in caplog.text

    def test_a_raising_fallback_is_logged_and_does_not_escape(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handlers = InteractionHandlers()

        def boom(_m: RemoteEventHandlerInvocation) -> None:
            raise ValueError("fallback failed")

        handlers.set_fallback(boom)

        with caplog.at_level(logging.ERROR):
            handlers.run(_click())

        assert "Fallback handler error for b1:click" in caplog.text
