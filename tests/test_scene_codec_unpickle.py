"""``scene_codec._unpickle`` rejects an undecodable or non-element pickle by name.

Pickling is the only Hub-to-Display transport, so a pickle that names a renamed
or deleted class — a version-skewed Hub/Display pair, the stale-restart failure
mode — must not crash the display. The reader's socket boundary catches
``ValueError`` / ``KeyError`` / ``TypeError``; ``_unpickle`` converts the
``AttributeError`` / ``ImportError`` a bad class reference raises into the named
``ValueError``, and rejects a pickle of a non-element the same way, so the
display records the error and survives.
"""

from __future__ import annotations

import base64
import pickle
import socket
import tempfile
from pathlib import Path

import pytest

from punt_lux.protocol import ReadyMessage, encode_frame, recv_message
from punt_lux.protocol.messages.scene_codec import SceneCodec
from punt_lux.socket_server import SocketServer

# A pickle whose GLOBAL opcode names a module that does not exist — exactly what
# a renamed or deleted element class produces at the receiving tier. Raw
# ``pickle.loads`` raises ``ModuleNotFoundError`` (an ``ImportError``), which the
# pre-fix catch missed and which would escape the socket boundary.
_DELETED_CLASS_PICKLE = base64.b64encode(
    b"c__deleted_module__\nRenamedElement\n)\x81."
).decode()


def _scene_wire(pickled_b64: str) -> dict[str, object]:
    """A minimal scene wire dict whose one element is a raw ``_pickled`` entry."""
    return {
        "type": "scene",
        "id": "s1",
        "frame_id": "s1",
        "elements": [{"_pickled": pickled_b64}],
    }


def test_undecodable_pickle_is_rejected_by_name() -> None:
    """A pickle naming a deleted class becomes the named ValueError, not ImportError."""
    with pytest.raises(ValueError, match="_pickled is not decodable"):
        SceneCodec.decode(_scene_wire(_DELETED_CLASS_PICKLE))


def test_pickled_non_element_is_rejected_by_name() -> None:
    """A pickle of a non-element is rejected here, not later in the wrap path."""
    not_an_element = base64.b64encode(pickle.dumps({"a": 1})).decode()
    with pytest.raises(ValueError, match="_pickled is not an Element"):
        SceneCodec.decode(_scene_wire(not_an_element))


def test_display_survives_an_undecodable_pickle_frame() -> None:
    """A bad-pickle frame is recorded and the client dropped — the display lives.

    Drives the real socket boundary: the reader decodes the frame, ``_unpickle``
    raises the named ``ValueError``, and the boundary's ``except`` records it and
    removes the client instead of letting an ``AttributeError`` kill the process.
    """
    tmpdir = tempfile.mkdtemp(prefix="lux-")
    sock_path = Path(tmpdir) / "d.sock"
    errors: list[tuple[str, str, str]] = []
    server = SocketServer(
        on_message=lambda _sock, _msg: None,
        on_client_disconnected=lambda _fd: None,
        on_error=lambda sev, msg, ctx: errors.append((sev, msg, ctx)),
    )
    try:
        server.setup(sock_path)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(sock_path))
        try:
            server.accept_connections()
            assert isinstance(recv_message(client, timeout=2.0), ReadyMessage)

            client.sendall(encode_frame(_scene_wire(_DELETED_CLASS_PICKLE)))
            server.poll_clients()  # must not raise — the display survives

            assert any(ctx == "message_parse" for _sev, _msg, ctx in errors)
            assert "not decodable" in " ".join(msg for _sev, msg, _ctx in errors)
            assert len(server.clients) == 0  # the offending client was removed
        finally:
            client.close()
    finally:
        server.shutdown()
