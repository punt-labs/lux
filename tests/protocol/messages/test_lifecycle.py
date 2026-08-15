"""Lifecycle message codecs — roundtrips and decode errors.

Every class in ``protocol/messages/lifecycle.py`` now serializes itself
(``to_dict``/``from_dict``) rather than being serialized by a free function
(PY-OO-5). These tests exercise that contract directly, plus the two wire
additions DES-068 needs: ``ConnectMessage.kind`` and ``HubManifestMessage``.
"""

from __future__ import annotations

import pytest

from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.lifecycle import (
    AckMessage,
    ConnectMessage,
    HubManifestMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
)
from punt_lux.protocol.messages.unknown_message import UnknownMessage


class TestPingMessage:
    def test_roundtrip_with_timestamp(self) -> None:
        original = PingMessage(ts=1.5)
        restored = PingMessage.from_dict(original.to_dict())
        assert restored == original

    def test_roundtrip_without_timestamp(self) -> None:
        original = PingMessage()
        d = original.to_dict()
        assert "ts" not in d
        assert PingMessage.from_dict(d) == original


class TestConnectMessage:
    def test_roundtrip_preserves_kind(self) -> None:
        original = ConnectMessage(name="lux-mcp", kind="hub")
        d = original.to_dict()
        assert d["kind"] == "hub"
        restored = ConnectMessage.from_dict(d)
        assert restored == original

    def test_roundtrip_preserves_test_kind(self) -> None:
        original = ConnectMessage(name="probe", kind="test")
        d = original.to_dict()
        assert d["kind"] == "test"
        restored = ConnectMessage.from_dict(d)
        assert restored == original

    def test_decode_rejects_missing_kind(self) -> None:
        """No default -- every caller must declare 'hub' or 'test' explicitly."""
        with pytest.raises(ValueError, match="missing or invalid 'kind'"):
            ConnectMessage.from_dict({"type": "connect", "name": "quarry"})

    def test_decode_rejects_missing_name(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'name'"):
            ConnectMessage.from_dict({"type": "connect", "kind": "test"})

    def test_decode_rejects_blank_name(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'name'"):
            ConnectMessage.from_dict({"type": "connect", "name": "   ", "kind": "test"})

    def test_decode_rejects_invalid_kind(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'kind'"):
            ConnectMessage.from_dict({"type": "connect", "name": "x", "kind": "bogus"})

    def test_registry_roundtrip(self) -> None:
        original = ConnectMessage(name="lux-mcp", kind="hub")
        restored = message_from_dict(message_to_dict(original))
        assert restored == original


class TestHubManifestMessage:
    def test_roundtrip_with_scenes(self) -> None:
        original = HubManifestMessage(scene_ids=("s1", "s2"))
        restored = HubManifestMessage.from_dict(original.to_dict())
        assert restored == original

    def test_roundtrip_empty(self) -> None:
        """A fresh Hub restart declares an empty manifest — the common case."""
        original = HubManifestMessage(scene_ids=())
        d = original.to_dict()
        assert d["scene_ids"] == []
        assert HubManifestMessage.from_dict(d) == original

    def test_decode_defaults_missing_scene_ids_to_empty(self) -> None:
        restored = HubManifestMessage.from_dict({"type": "hub_manifest"})
        assert restored.scene_ids == ()

    def test_registry_roundtrip(self) -> None:
        original = HubManifestMessage(scene_ids=("a", "b", "c"))
        restored = message_from_dict(message_to_dict(original))
        assert restored == original
        assert message_to_dict(original)["type"] == "hub_manifest"

    def test_decode_rejects_a_bare_string_scene_ids(self) -> None:
        """A string is iterable, so a naive ``tuple(raw)`` would silently
        purge every real scene against its individual characters."""
        with pytest.raises(ValueError, match="must be a list"):
            HubManifestMessage.from_dict({"type": "hub_manifest", "scene_ids": "s1"})

    def test_decode_rejects_non_string_elements(self) -> None:
        with pytest.raises(ValueError, match=r"scene_ids\[1\] must be a string"):
            HubManifestMessage.from_dict(
                {"type": "hub_manifest", "scene_ids": ["s1", 2, "s3"]}
            )


class TestReadyMessage:
    def test_roundtrip_with_capabilities(self) -> None:
        original = ReadyMessage(capabilities=["screenshot"])
        restored = ReadyMessage.from_dict(original.to_dict())
        assert restored == original

    def test_roundtrip_without_capabilities(self) -> None:
        original = ReadyMessage()
        d = original.to_dict()
        assert "capabilities" not in d
        assert ReadyMessage.from_dict(d) == original


class TestAckMessage:
    def test_roundtrip_success(self) -> None:
        original = AckMessage(scene_id="s1", ts=2.0)
        restored = AckMessage.from_dict(original.to_dict())
        assert restored == original

    def test_roundtrip_error(self) -> None:
        original = AckMessage(scene_id="s1", error="boom")
        restored = AckMessage.from_dict(original.to_dict())
        assert restored == original


class TestPongMessage:
    def test_roundtrip(self) -> None:
        original = PongMessage(ts=1.0, display_ts=2.0)
        restored = PongMessage.from_dict(original.to_dict())
        assert restored == original

    def test_roundtrip_no_timestamps(self) -> None:
        original = PongMessage()
        d = original.to_dict()
        assert "ts" not in d
        assert "display_ts" not in d
        assert PongMessage.from_dict(d) == original


class TestUnknownMessage:
    def test_roundtrip_preserves_raw_type_and_payload(self) -> None:
        original = UnknownMessage(raw_type="future_kind", data={"foo": "bar"})
        d = original.to_dict()
        assert d["type"] == "future_kind"
        assert d["foo"] == "bar"
        restored = UnknownMessage.from_dict(d)
        assert restored.raw_type == "future_kind"
        assert restored.data == d

    def test_from_dict_copies_the_input_dict(self) -> None:
        """The dataclass is frozen, but a dict stored by reference is not.

        A caller mutating the dict it handed to ``from_dict`` must not reach
        through to the message's own ``data``.
        """
        source = {"type": "future_kind", "foo": "bar"}
        restored = UnknownMessage.from_dict(source)
        source["foo"] = "mutated"
        assert restored.data["foo"] == "bar"
