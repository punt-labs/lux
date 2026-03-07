"""Unit tests for punt_lux.server — MCP tool functions."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from punt_lux.protocol import (
    AckMessage,
    InteractionMessage,
    PongMessage,
    element_from_dict,
)
from punt_lux.server import clear, ping, recv, show, update


class TestElementFromDict:
    def test_text_element(self) -> None:
        elem = element_from_dict(
            {"kind": "text", "id": "t1", "content": "Hello", "style": "heading"}
        )
        assert elem.kind == "text"
        assert elem.id == "t1"

    def test_button_element(self) -> None:
        elem = element_from_dict({"kind": "button", "id": "b1", "label": "Click"})
        assert elem.kind == "button"

    def test_image_element(self) -> None:
        elem = element_from_dict({"kind": "image", "id": "i1", "path": "/img.png"})
        assert elem.kind == "image"

    def test_separator_element(self) -> None:
        elem = element_from_dict({"kind": "separator"})
        assert elem.kind == "separator"

    def test_default_kind_is_text(self) -> None:
        elem = element_from_dict({"id": "t1", "content": "Hi"})
        assert elem.kind == "text"

    def test_text_defaults_content_to_empty(self) -> None:
        elem = element_from_dict({"kind": "text", "id": "t1"})
        assert elem.content == ""  # type: ignore[union-attr]

    def test_button_defaults_label_to_empty(self) -> None:
        elem = element_from_dict({"kind": "button", "id": "b1"})
        assert elem.label == ""  # type: ignore[union-attr]

    def test_unknown_kind_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown element kind"):
            element_from_dict({"kind": "bogus", "id": "x"})


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


class TestShowTool:
    @patch("punt_lux.server._get_client")
    def test_show_returns_ack(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="s1", ts=time.time())
        mock_get.return_value = client

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])
        assert result == "ack:s1"
        client.show.assert_called_once()

    @patch("punt_lux.server._get_client")
    def test_show_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = None
        mock_get.return_value = client

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])
        assert result == "timeout"


class TestUpdateTool:
    @patch("punt_lux.server._get_client")
    def test_update_returns_ack(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.update.return_value = AckMessage(scene_id="s1", ts=time.time())
        mock_get.return_value = client

        result = update("s1", [{"id": "t1", "set": {"content": "New"}}])
        assert result == "ack:s1"

    @patch("punt_lux.server._get_client")
    def test_update_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.update.return_value = None
        mock_get.return_value = client

        result = update("s1", [{"id": "t1", "set": {"content": "New"}}])
        assert result == "timeout"


class TestClearTool:
    @patch("punt_lux.server._get_client")
    def test_clear_returns_cleared(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = clear()
        assert result == "cleared"
        client.clear.assert_called_once()


class TestPingTool:
    @patch("punt_lux.server.time")
    @patch("punt_lux.server._get_client")
    def test_ping_returns_rtt(self, mock_get: MagicMock, mock_time: MagicMock) -> None:
        client = _mock_client()
        ts = 1000.0
        mock_time.time.return_value = ts + 0.042
        client.ping.return_value = PongMessage(ts=ts, display_ts=ts + 0.005)
        mock_get.return_value = client

        result = ping()
        assert result == "pong:rtt=0.042s"

    @patch("punt_lux.server._get_client")
    def test_ping_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.ping.return_value = None
        mock_get.return_value = client

        result = ping()
        assert result == "timeout"


class TestRecvTool:
    @patch("punt_lux.server._get_client")
    def test_recv_interaction(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.recv.return_value = InteractionMessage(
            element_id="b1", action="click", ts=time.time(), value=True
        )
        mock_get.return_value = client

        result = recv(timeout=1.0)
        assert "interaction" in result
        assert "b1" in result
        assert "click" in result

    @patch("punt_lux.server._get_client")
    def test_recv_none(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.recv.return_value = None
        mock_get.return_value = client

        result = recv(timeout=0.1)
        assert result == "none"
