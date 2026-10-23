"""A display that answers with a scene -- or a bomb -- never reaches the decoder.

Every Hub-side read of the display's reply checks the frame's raw ``type``
against what a display may send BEFORE decoding, and bounds the JSON nesting, so
a hostile peer can neither make luxd unpickle a scene's elements nor kill a
reader with a deeply nested frame.
"""

from __future__ import annotations

import base64
import pickle
import socket
import struct
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

import pytest

from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.paths import DisplayPaths, SocketLiveness
from punt_lux.protocol import (
    HEADER_FORMAT,
    FrameReader,
    ReadyMessage,
    decode_frame,
    encode_frame,
    recv_message,
    send_message,
)
from punt_lux.protocol.json_payload import MAX_NESTING, JsonPayload
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY

if TYPE_CHECKING:
    from collections.abc import Iterator


def _scene_frame() -> bytes:
    pickled = base64.b64encode(b"not really a pickle").decode("ascii")
    return encode_frame(
        {
            "type": "scene",
            "id": "s",
            "frame_id": "f",
            "elements": [{"_pickled": pickled}],
        }
    )


def _bomb_frame(depth: int = 100_000) -> bytes:
    payload = b"[" * depth + b"]" * depth
    return struct.pack(HEADER_FORMAT, len(payload)) + payload


@pytest.fixture
def unpickled(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Record every ``pickle.loads`` call; the hostile paths must make none."""
    calls: list[bytes] = []

    def spy(data: bytes) -> None:
        calls.append(data)

    monkeypatch.setattr(pickle, "loads", spy)
    return calls


@final
class _HostileDisplay:
    """A display at a socket path: optionally greets, then answers with ``reply``."""

    _reply: bytes
    _greets: bool
    _server: socket.socket
    _thread: threading.Thread
    path: Path

    def __new__(cls, reply: bytes, *, greets: bool) -> Self:
        self = super().__new__(cls)
        self._reply = reply
        self._greets = greets
        self.path = Path(tempfile.mkdtemp(prefix="lux-")) / "d.sock"
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.path))
        self._server.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        conn, _ = self._server.accept()
        with conn:
            if self._greets:
                send_message(conn, ReadyMessage())
                self._await_frames(conn, 1)  # the request
            conn.sendall(self._reply)
            self._thread_wait(conn)

    @staticmethod
    def _await_frames(conn: socket.socket, count: int) -> None:
        reader = FrameReader()
        seen = 0
        conn.settimeout(3.0)
        while seen < count:
            reader.feed(conn.recv(65536))
            seen += len(reader.drain())

    @staticmethod
    def _thread_wait(conn: socket.socket) -> None:
        conn.settimeout(3.0)
        try:
            conn.recv(1)
        except (TimeoutError, OSError):
            return

    def stop(self) -> None:
        self._server.close()
        self._thread.join(timeout=5)


@pytest.fixture
def hostile() -> Iterator[Callable[[bytes, bool], _HostileDisplay]]:
    made: list[_HostileDisplay] = []

    def make(reply: bytes, greets: bool) -> _HostileDisplay:
        display = _HostileDisplay(reply, greets=greets)
        made.append(display)
        return display

    yield make
    for display in made:
        display.stop()


if TYPE_CHECKING:
    from collections.abc import Callable


class TestScenesFromADisplay:
    def test_recv_message_refuses_a_scene_before_unpickling(
        self, unpickled: list[bytes]
    ) -> None:
        ours, theirs = socket.socketpair()
        with ours, theirs:
            theirs.sendall(_scene_frame())
            with pytest.raises(ValueError, match="not accepted"):
                recv_message(ours, DISPLAY_VOCABULARY, timeout=2.0)
        assert unpickled == []

    def test_the_handshake_refuses_a_scene_in_place_of_ready(
        self,
        hostile: Callable[[bytes, bool], _HostileDisplay],
        unpickled: list[bytes],
    ) -> None:
        display = hostile(_scene_frame(), False)
        # The scene arrives where the ReadyMessage should: send it on accept.
        link = DisplayLink(display.path, auto_spawn=False, connect_timeout=2.0)

        with pytest.raises(ValueError, match="not accepted"):
            link.connect()

        assert unpickled == []

    def test_an_inline_ping_refuses_a_scene_reply(
        self,
        hostile: Callable[[bytes, bool], _HostileDisplay],
        unpickled: list[bytes],
    ) -> None:
        display = hostile(_scene_frame(), True)
        with DisplayLink(display.path, auto_spawn=False, connect_timeout=2.0) as link:
            link.connect()
            with pytest.raises(ValueError, match="not accepted"):
                link.ping(timeout=2.0)
        assert unpickled == []

    def test_an_inline_ack_wait_refuses_a_scene_reply(
        self,
        hostile: Callable[[bytes, bool], _HostileDisplay],
        unpickled: list[bytes],
    ) -> None:
        display = hostile(_scene_frame(), True)
        with DisplayLink(display.path, auto_spawn=False, connect_timeout=2.0) as link:
            link.connect()
            with pytest.raises(ValueError, match="not accepted"):
                link.show("s", [])
        assert unpickled == []

    def test_the_liveness_probe_never_unpickles_a_squatters_scene(
        self,
        hostile: Callable[[bytes, bool], _HostileDisplay],
        unpickled: list[bytes],
    ) -> None:
        display = hostile(_scene_frame(), False)

        assert DisplayPaths(display.path)._probe() is SocketLiveness.ACCEPTING
        assert unpickled == []


class TestDeepFrames:
    def test_a_frame_nested_past_the_bound_is_a_value_error(self) -> None:
        reader = FrameReader()
        reader.feed(_bomb_frame())

        with pytest.raises(ValueError, match="nests"):
            list(reader.iter_typed(DISPLAY_VOCABULARY))

    def test_decode_frame_refuses_a_deep_frame(self) -> None:
        with pytest.raises(ValueError, match="nests"):
            decode_frame(_bomb_frame())

    def test_recv_message_refuses_a_deep_frame(self) -> None:
        ours, theirs = socket.socketpair()
        with ours, theirs:
            theirs.sendall(_bomb_frame())
            with pytest.raises(ValueError, match="nests"):
                recv_message(ours, DISPLAY_VOCABULARY, timeout=2.0)

    def test_nesting_at_the_bound_is_decoded(self) -> None:
        depth = MAX_NESTING - 1
        payload = b'{"k": ' + b"[" * depth + b"]" * depth + b"}"

        assert JsonPayload(payload).as_object() == {"k": _nest(depth)}

    def test_brackets_inside_strings_do_not_count(self) -> None:
        payload = b'{"text": "' + b"[" * 500 + b'"}'

        assert JsonPayload(payload).as_object() == {"text": "[" * 500}

    def test_recursion_error_from_the_decoder_becomes_a_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(_raw: bytes) -> object:
            raise RecursionError

        monkeypatch.setattr("punt_lux.protocol.json_payload.json.loads", boom)

        with pytest.raises(ValueError, match="nests too deeply"):
            JsonPayload(b"{}").as_object()


def _nest(depth: int) -> list[object]:
    value: list[object] = []
    for _ in range(depth - 1):
        value = [value]
    return value
