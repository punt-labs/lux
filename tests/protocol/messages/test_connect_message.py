"""ConnectMessage codec — roundtrips and decode errors, hub_id included (W2)."""

from __future__ import annotations

import pytest

from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.connect_message import ConnectMessage


class TestConnectMessage:
    def test_roundtrip_preserves_kind(self) -> None:
        original = ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123")
        d = original.to_dict()
        assert d["kind"] == "hub"
        restored = ConnectMessage.from_dict(d)
        assert restored == original

    def test_roundtrip_preserves_test_kind(self) -> None:
        original = ConnectMessage(name="probe", kind="test", hub_id="test.invalid\x1f0")
        d = original.to_dict()
        assert d["kind"] == "test"
        restored = ConnectMessage.from_dict(d)
        assert restored == original

    def test_roundtrip_preserves_hub_id(self) -> None:
        original = ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123")
        d = original.to_dict()
        assert d["hub_id"] == "pembroke\x1f123"
        restored = ConnectMessage.from_dict(d)
        assert restored.hub_id == "pembroke\x1f123"

    def test_decode_rejects_missing_kind(self) -> None:
        """No default -- every caller must declare 'hub' or 'test' explicitly."""
        with pytest.raises(ValueError, match="missing or invalid 'kind'"):
            ConnectMessage.from_dict(
                {"type": "connect", "name": "quarry", "hub_id": "x\x1f1"}
            )

    def test_decode_rejects_missing_name(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'name'"):
            ConnectMessage.from_dict(
                {"type": "connect", "kind": "test", "hub_id": "x\x1f1"}
            )

    def test_decode_rejects_blank_name(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'name'"):
            ConnectMessage.from_dict(
                {
                    "type": "connect",
                    "name": "   ",
                    "kind": "test",
                    "hub_id": "x\x1f1",
                }
            )

    def test_decode_rejects_invalid_kind(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'kind'"):
            ConnectMessage.from_dict(
                {
                    "type": "connect",
                    "name": "x",
                    "kind": "bogus",
                    "hub_id": "x\x1f1",
                }
            )

    def test_decode_rejects_missing_hub_id(self) -> None:
        """Required for every kind, including 'test' -- a stub, never an absence."""
        with pytest.raises(ValueError, match="missing or invalid 'hub_id'"):
            ConnectMessage.from_dict(
                {"type": "connect", "name": "quarry", "kind": "test"}
            )

    def test_decode_rejects_blank_hub_id(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'hub_id'"):
            ConnectMessage.from_dict(
                {"type": "connect", "name": "quarry", "kind": "test", "hub_id": "   "}
            )

    def test_registry_roundtrip(self) -> None:
        original = ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123")
        restored = message_from_dict(message_to_dict(original))
        assert restored == original
