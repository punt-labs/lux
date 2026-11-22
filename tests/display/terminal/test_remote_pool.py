"""Reply correlation preserves the pool's handshake and channel boundaries."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest

from punt_lux.display.terminal.attachment_requests import AttachmentRequests
from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_pool import RemotePool


class TestRemotePoolReplies:
    def test_first_ready_reply_attaches_existing_sessions(self) -> None:
        pool = RemotePool(Path("/nonexistent/pty.sock"))
        session = pool.get("shell", "sh")
        with (
            patch.object(
                AttachmentRequests,
                "ready",
                new_callable=PropertyMock,
                side_effect=[False, True],
            ),
            patch.object(AttachmentRequests, "receive", return_value=None),
            patch.object(pool, "_attach") as attach,
        ):
            pool._reply(b"hello")
        attach.assert_called_once_with(session)
        assert pool._channels == {}

    @pytest.mark.parametrize("ready", [False, True])
    def test_reply_without_session_does_not_register_a_channel(
        self, ready: bool
    ) -> None:
        pool = RemotePool(Path("/nonexistent/pty.sock"))
        with (
            patch.object(
                AttachmentRequests,
                "ready",
                new_callable=PropertyMock,
                return_value=ready,
            ),
            patch.object(AttachmentRequests, "receive", return_value=None),
            patch.object(pool, "_attach") as attach,
        ):
            pool._reply(b"reply")
        attach.assert_not_called()
        assert pool._channels == {}

    def test_attach_reply_registers_the_session_channel(self) -> None:
        pool = RemotePool(Path("/nonexistent/pty.sock"))
        session = pool.get("shell", "sh")
        with (
            patch.object(
                AttachmentRequests,
                "ready",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(AttachmentRequests, "receive", return_value=session),
            patch.object(
                RemoteSession, "channel", new_callable=PropertyMock, return_value=3
            ),
        ):
            pool._reply(b"attached")
        assert pool._channels == {3: session}

    def test_duplicate_channel_is_rejected_without_replacing_the_session(self) -> None:
        pool = RemotePool(Path("/nonexistent/pty.sock"))
        existing = pool.get("existing", "sh")
        pending = pool.get("pending", "sh")
        pool._channels[3] = existing
        with (
            patch.object(
                AttachmentRequests,
                "ready",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(AttachmentRequests, "receive", return_value=pending),
            patch.object(
                RemoteSession, "channel", new_callable=PropertyMock, return_value=3
            ),
            pytest.raises(ValueError, match="duplicate terminal channel"),
        ):
            pool._reply(b"duplicate")
        assert pool._channels == {3: existing}

    def test_invalid_reply_propagates_without_registering_a_channel(self) -> None:
        pool = RemotePool(Path("/nonexistent/pty.sock"))
        with (
            patch.object(
                AttachmentRequests, "receive", side_effect=ValueError("invalid")
            ),
            pytest.raises(ValueError, match="invalid"),
        ):
            pool._reply(b"invalid")
        assert pool._channels == {}
