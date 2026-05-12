"""Tests for the generic QueryRequest/QueryResponse infrastructure."""

from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from punt_lux.display_client import DisplayClient
from punt_lux.protocol import (
    AckMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    SceneMessage,
    TextElement,
    message_from_dict,
    message_to_dict,
    recv_message,
    send_message,
)

# ---------------------------------------------------------------------------
# Protocol round-trip tests
# ---------------------------------------------------------------------------


class TestQueryProtocol:
    def test_query_request_defaults(self) -> None:
        msg = QueryRequest(method="get_display_info")
        assert msg.type == "query_request"
        assert msg.method == "get_display_info"
        assert msg.params == {}

    def test_query_request_with_params(self) -> None:
        msg = QueryRequest(method="inspect_scene", params={"scene_id": "s1"})
        assert msg.params == {"scene_id": "s1"}

    def test_query_request_roundtrip(self) -> None:
        original = QueryRequest(method="inspect_scene", params={"scene_id": "test"})
        d = message_to_dict(original)
        assert d["type"] == "query_request"
        assert d["method"] == "inspect_scene"
        assert d["params"] == {"scene_id": "test"}
        restored = message_from_dict(d)
        assert isinstance(restored, QueryRequest)
        assert restored.method == "inspect_scene"
        assert restored.params == {"scene_id": "test"}

    def test_query_request_empty_params_omitted(self) -> None:
        original = QueryRequest(method="list_scenes")
        d = message_to_dict(original)
        assert d["type"] == "query_request"
        assert d["method"] == "list_scenes"
        assert "params" not in d

    def test_query_request_from_dict_missing_params(self) -> None:
        d: dict[str, Any] = {"type": "query_request", "method": "list_scenes"}
        msg = message_from_dict(d)
        assert isinstance(msg, QueryRequest)
        assert msg.params == {}

    def test_query_response_defaults(self) -> None:
        msg = QueryResponse(method="get_display_info")
        assert msg.type == "query_response"
        assert msg.method == "get_display_info"
        assert msg.result == {}
        assert msg.error is None

    def test_query_response_with_result(self) -> None:
        msg = QueryResponse(
            method="get_display_info",
            result={"backend": "opengl3", "fps": 60.0},
        )
        assert msg.result == {"backend": "opengl3", "fps": 60.0}

    def test_query_response_with_error(self) -> None:
        msg = QueryResponse(method="unknown", error="Unknown method: unknown")
        assert msg.error == "Unknown method: unknown"
        assert msg.result == {}

    def test_query_response_roundtrip(self) -> None:
        original = QueryResponse(
            method="get_display_info",
            result={"backend": "opengl3", "pid": 12345},
        )
        d = message_to_dict(original)
        assert d["type"] == "query_response"
        assert d["method"] == "get_display_info"
        assert d["result"] == {"backend": "opengl3", "pid": 12345}
        assert "error" not in d
        restored = message_from_dict(d)
        assert isinstance(restored, QueryResponse)
        assert restored.method == "get_display_info"
        assert restored.result == {"backend": "opengl3", "pid": 12345}
        assert restored.error is None

    def test_query_response_error_roundtrip(self) -> None:
        original = QueryResponse(
            method="bad_method", error="Unknown method: bad_method"
        )
        d = message_to_dict(original)
        assert d["error"] == "Unknown method: bad_method"
        assert d["result"] == {}
        restored = message_from_dict(d)
        assert isinstance(restored, QueryResponse)
        assert restored.error == "Unknown method: bad_method"

    def test_message_from_dict_recognizes_query_request(self) -> None:
        d: dict[str, Any] = {
            "type": "query_request",
            "method": "list_clients",
            "params": {"verbose": True},
        }
        msg = message_from_dict(d)
        assert isinstance(msg, QueryRequest)
        assert msg.method == "list_clients"
        assert msg.params == {"verbose": True}

    def test_message_from_dict_recognizes_query_response(self) -> None:
        d: dict[str, Any] = {
            "type": "query_response",
            "method": "list_clients",
            "result": {"clients": []},
        }
        msg = message_from_dict(d)
        assert isinstance(msg, QueryResponse)
        assert msg.method == "list_clients"
        assert msg.result == {"clients": []}


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def _short_sock_path() -> tuple[str, Path]:
    """Create a short temp dir + socket path (Unix sockets have ~104 char limit)."""
    d = tempfile.mkdtemp(prefix="lux-")
    return d, Path(d) / "d.sock"


def _cleanup(short_dir: str, *socks: socket.socket | None) -> None:
    import contextlib
    import shutil

    for s in socks:
        if s is not None:
            with contextlib.suppress(OSError):
                s.close()
    shutil.rmtree(short_dir, ignore_errors=True)


def _mini_query_server(
    sock_path: Path,
    ready: threading.Event,
    handler: Any = None,
) -> socket.socket:
    """Start a mini server that accepts one client and sends ReadyMessage.

    Returns the server-side connection socket. The caller owns both
    the returned connection and the listening socket (closed here).
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(sock_path))
        server.listen(1)
        ready.set()
        conn, _ = server.accept()
        send_message(conn, ReadyMessage())
        return conn
    finally:
        server.close()


def _serve_queries(
    conn: socket.socket,
    count: int,
    stop: threading.Event,
) -> None:
    """Read *count* messages and respond to QueryRequests."""
    for _ in range(count):
        if stop.is_set():
            break
        msg = recv_message(conn, timeout=5)
        if msg is None:
            break
        if isinstance(msg, QueryRequest):
            if msg.method == "echo":
                resp = QueryResponse(
                    method=msg.method,
                    result={"echo": msg.params},
                )
            elif msg.method == "error_test":
                resp = QueryResponse(
                    method=msg.method,
                    error="deliberate test error",
                )
            else:
                resp = QueryResponse(
                    method=msg.method,
                    result={"handled": True},
                )
            send_message(conn, resp)
        elif isinstance(msg, SceneMessage):
            send_message(conn, AckMessage(scene_id=msg.id, ts=time.time()))


# ---------------------------------------------------------------------------
# Client query() integration tests
# ---------------------------------------------------------------------------


class TestClientQuery:
    @pytest.mark.integration
    def test_query_returns_response(self) -> None:
        """query() sends a QueryRequest and receives a QueryResponse."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()
        stop_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_query_server(sock_path, ready_event)
            _serve_queries(server_conn, 1, stop_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                resp = client.query("echo", {"key": "value"})
                assert resp is not None
                assert isinstance(resp, QueryResponse)
                assert resp.method == "echo"
                assert resp.result == {"echo": {"key": "value"}}
                assert resp.error is None
        finally:
            stop_event.set()
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)

    @pytest.mark.integration
    def test_query_error_response(self) -> None:
        """query() receives error responses correctly."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()
        stop_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_query_server(sock_path, ready_event)
            _serve_queries(server_conn, 1, stop_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                resp = client.query("error_test")
                assert resp is not None
                assert resp.error == "deliberate test error"
        finally:
            stop_event.set()
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)

    @pytest.mark.integration
    def test_query_timeout_returns_none(self) -> None:
        """query() returns None when the server does not respond."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(sock_path))
            server.listen(1)
            ready_event.set()
            conn, _ = server.accept()
            send_message(conn, ReadyMessage())
            server_conn = conn
            # Do NOT read or respond — let the client time out
            time.sleep(3)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0, recv_timeout=0.3
            ) as client:
                resp = client.query("anything", timeout=0.3)
                assert resp is None
        finally:
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)

    @pytest.mark.integration
    def test_query_with_listener(self) -> None:
        """query() works when the background listener is active."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()
        stop_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_query_server(sock_path, ready_event)
            _serve_queries(server_conn, 2, stop_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                client.start_listener()
                resp = client.query("echo", {"data": 42})
                assert resp is not None
                assert resp.method == "echo"
                assert resp.result == {"echo": {"data": 42}}
        finally:
            stop_event.set()
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)

    @pytest.mark.integration
    def test_query_interleaved_with_scene(self) -> None:
        """query() and show() can be interleaved without confusion."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()
        stop_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_query_server(sock_path, ready_event)
            _serve_queries(server_conn, 2, stop_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                # First: send a scene
                ack = client.show(
                    "s1",
                    elements=[TextElement(id="t1", content="hi")],
                )
                assert ack is not None
                assert ack.scene_id == "s1"

                # Second: send a query
                resp = client.query("echo", {"after_scene": True})
                assert resp is not None
                assert resp.method == "echo"
        finally:
            stop_event.set()
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)
