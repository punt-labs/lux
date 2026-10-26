"""ClientQueries -- every question a client asks is answered through the reply door."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from punt_lux.display.client_queries import ClientQueries
from punt_lux.display.window_settings import WindowSettings
from punt_lux.protocol import (
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ScreenshotRequest,
    ScreenshotResponse,
    UnknownMessage,
)

if TYPE_CHECKING:
    import socket


_SOCK = cast("socket.socket", object())


def _queries(
    answers: dict[str, SimpleNamespace] | None = None,
) -> tuple[ClientQueries, MagicMock, MagicMock]:
    sender, router = MagicMock(), MagicMock()

    def answer_for(method: str, _params: object) -> SimpleNamespace:
        return (answers or {})[method]

    router.handle_query.side_effect = answer_for
    queries = ClientQueries(
        sender=sender,
        query_router=router,
        scenes=MagicMock(),
        geometry=MagicMock(),
        settings=WindowSettings(),
    )
    return queries, sender, router


def _answer(result: dict[str, object] | None = None, error: str | None = None):
    return SimpleNamespace(result=result or {}, error=error)


class TestTheHandlersItRegisters:
    def test_the_router_is_told_who_answers_each_generic_query(self) -> None:
        _, _sender, router = _queries()

        registered = {call.args[0] for call in router.register_handler.call_args_list}

        assert registered == {
            "inspect_scene",
            "screenshot",
            "get_display_info",
            "get_window_settings",
            "get_theme",
            "set_frame_state",
        }


class TestEveryAnswerLeavesByTheReplyDoor:
    def test_a_ping_is_answered_with_its_own_timestamp(self) -> None:
        queries, sender, _router = _queries()

        queries.handle(_SOCK, PingMessage(ts=7.0))

        ((sock, pong),) = [c.args for c in sender.reply_to_client.call_args_list]
        assert sock is _SOCK
        assert isinstance(pong, PongMessage)
        assert pong.ts == 7.0

    def test_an_introspection_returns_the_elements(self) -> None:
        queries, sender, _router = _queries(
            {"inspect_scene": _answer({"elements": [{"id": "e"}]})}
        )

        queries.handle(_SOCK, IntrospectRequest(scene_id="s"))

        ((_, reply),) = [c.args for c in sender.reply_to_client.call_args_list]
        assert isinstance(reply, IntrospectResponse)
        assert reply.elements == [{"id": "e"}]

    def test_an_introspection_that_failed_carries_the_error(self) -> None:
        queries, sender, _router = _queries(
            {"inspect_scene": _answer(error="no such scene")}
        )

        queries.handle(_SOCK, IntrospectRequest(scene_id="s"))

        ((_, reply),) = [c.args for c in sender.reply_to_client.call_args_list]
        assert isinstance(reply, IntrospectResponse)
        assert reply.error == "no such scene"

    def test_a_scene_listing_returns_the_scenes_and_frames(self) -> None:
        queries, sender, _router = _queries(
            {"list_scenes": _answer({"scenes": [{"id": "s"}], "frames": []})}
        )

        queries.handle(_SOCK, ListScenesRequest())

        ((_, reply),) = [c.args for c in sender.reply_to_client.call_args_list]
        assert isinstance(reply, ListScenesResponse)
        assert reply.scenes == [{"id": "s"}]

    def test_a_scene_listing_that_failed_says_so_and_is_never_an_empty_success(
        self,
    ) -> None:
        queries, sender, _router = _queries({"list_scenes": _answer(error="boom")})

        queries.handle(_SOCK, ListScenesRequest())

        ((_, reply),) = [c.args for c in sender.reply_to_client.call_args_list]
        assert isinstance(reply, ListScenesResponse)
        assert reply.error == "boom"

    def test_a_generic_query_is_dispatched_by_its_method(self) -> None:
        response = QueryResponse(method="m", result={"k": 1})
        queries, sender, router = _queries()
        router.handle_query.side_effect = None
        router.handle_query.return_value = response

        queries.handle(_SOCK, QueryRequest(method="m", params={"a": 1}))

        router.handle_query.assert_called_once_with("m", {"a": 1})
        sender.reply_to_client.assert_called_once_with(_SOCK, response)


class TestTheQuestionsThatAreNotAnswered:
    def test_a_screenshot_waits_for_the_next_swap_a_second_is_refused_at_once(
        self,
    ) -> None:
        queries, sender, _router = _queries()

        queries.handle(_SOCK, ScreenshotRequest())
        sender.reply_to_client.assert_not_called()
        queries.handle(_SOCK, ScreenshotRequest())

        ((_, busy),) = [c.args for c in sender.reply_to_client.call_args_list]
        assert isinstance(busy, ScreenshotResponse)
        assert busy.error is not None

    def test_an_unknown_kind_is_ignored_and_logged_at_debug(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        queries, sender, _router = _queries()

        with caplog.at_level("DEBUG"):
            queries.handle(_SOCK, UnknownMessage(raw_type="mystery"))

        sender.reply_to_client.assert_not_called()
        assert "mystery" in caplog.text


class TestTheGenericScreenshotQuery:
    def test_is_refused_the_dedicated_request_message_is_required(self) -> None:
        _, _sender, router = _queries()
        handlers = {
            c.args[0]: c.args[1] for c in router.register_handler.call_args_list
        }

        with pytest.raises(RuntimeError, match="screenshot_request"):
            handlers["screenshot"]()
