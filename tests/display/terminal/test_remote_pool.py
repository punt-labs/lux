"""Reply correlation preserves the pool's handshake and channel boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.protocol.pty.frames import Frame, FrameKind


@pytest.fixture
def pool_and_peers() -> Iterator[tuple[RemotePool, MagicMock, MagicMock]]:
    with (
        patch(
            "punt_lux.display.terminal.remote_pool.AttachmentRequests", autospec=True
        ) as requests_type,
        patch(
            "punt_lux.display.terminal.remote_pool.TerminalConnection", autospec=True
        ) as connection_type,
    ):
        requests = requests_type.return_value
        requests.ready = False
        requests.due.return_value = ()
        connection = connection_type.return_value
        pool = RemotePool(Path("/nonexistent/pty.sock"))
        try:
            yield pool, requests, connection
        finally:
            pool.close()


class TestRemotePoolReplies:
    def test_first_ready_reply_attaches_existing_sessions(
        self, pool_and_peers: tuple[RemotePool, MagicMock, MagicMock]
    ) -> None:
        pool, requests, connection = pool_and_peers
        first = pool.get("first", "sh")
        second = pool.get("second", "sh")

        def ready_reply(data: bytes) -> None:
            requests.ready = True

        requests.receive.side_effect = ready_reply
        connection.pump.return_value = [Frame(0, FrameKind.DATA, b"hello")]
        assert pool.pump()
        requests.receive.assert_called_once_with(b"hello")
        assert requests.attach.call_args_list == [call(2, first), call(3, second)]
        requests.disconnect.assert_not_called()

    @pytest.mark.parametrize("ready", [False, True])
    def test_reply_without_session_does_not_register_a_channel(
        self, pool_and_peers: tuple[RemotePool, MagicMock, MagicMock], ready: bool
    ) -> None:
        pool, requests, connection = pool_and_peers
        session = pool.get("shell", "sh")
        requests.ready = ready
        requests.receive.return_value = None
        connection.pump.return_value = [
            Frame(0, FrameKind.DATA, b"reply"),
            Frame(3, FrameKind.DATA, b"output"),
        ]
        assert not pool.pump()
        requests.receive.assert_called_once_with(b"reply")
        requests.attach.assert_not_called()
        requests.disconnect.assert_called_once_with(
            (session,), "/nonexistent/pty.sock: unexpected terminal channel"
        )

    def test_attach_reply_registers_the_session_channel(
        self, pool_and_peers: tuple[RemotePool, MagicMock, MagicMock]
    ) -> None:
        pool, requests, connection = pool_and_peers
        session = pool.get("shell", "sh")
        requests.ready = True
        requests.receive.return_value = session
        output = Frame(3, FrameKind.DATA, b"output")
        connection.pump.return_value = [Frame(0, FrameKind.DATA, b"attached"), output]
        with (
            patch.object(
                RemoteSession, "channel", new_callable=PropertyMock, return_value=3
            ),
            patch.object(session, "receive") as receive,
        ):
            assert pool.pump()
        requests.receive.assert_called_once_with(b"attached")
        receive.assert_called_once_with(output)
        requests.disconnect.assert_not_called()

    def test_duplicate_channel_disconnects_without_delivering_to_pending_session(
        self, pool_and_peers: tuple[RemotePool, MagicMock, MagicMock]
    ) -> None:
        pool, requests, connection = pool_and_peers
        existing = pool.get("existing", "sh")
        pending = pool.get("pending", "sh")
        requests.ready = True
        requests.receive.side_effect = [existing, pending]
        output = Frame(3, FrameKind.DATA, b"output")
        connection.pump.return_value = [
            Frame(0, FrameKind.DATA, b"attached"),
            output,
            Frame(0, FrameKind.DATA, b"duplicate"),
            output,
        ]
        with (
            patch.object(
                RemoteSession, "channel", new_callable=PropertyMock, return_value=3
            ),
            patch.object(existing, "receive") as existing_receive,
            patch.object(pending, "receive") as pending_receive,
        ):
            assert not pool.pump()
        assert requests.receive.call_args_list == [
            call(b"attached"),
            call(b"duplicate"),
        ]
        existing_receive.assert_called_once_with(output)
        pending_receive.assert_not_called()
        requests.disconnect.assert_called_once_with(
            (existing, pending), "/nonexistent/pty.sock: duplicate terminal channel"
        )

    def test_invalid_reply_disconnects_the_pool(
        self, pool_and_peers: tuple[RemotePool, MagicMock, MagicMock]
    ) -> None:
        pool, requests, connection = pool_and_peers
        session = pool.get("shell", "sh")
        requests.receive.side_effect = ValueError("invalid")
        connection.pump.return_value = [Frame(0, FrameKind.DATA, b"invalid")]
        assert not pool.pump()
        requests.receive.assert_called_once_with(b"invalid")
        requests.disconnect.assert_called_once_with(
            (session,), "/nonexistent/pty.sock: invalid"
        )
        connection.close.assert_called_once_with()
