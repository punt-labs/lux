"""RemoteEventHandlerInvocation codec — roundtrips, and ``hub_token`` stays
Display-local (W6, never crosses the wire)."""

from __future__ import annotations

from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation


class TestRemoteEventHandlerInvocation:
    def test_roundtrip_preserves_element_and_action(self) -> None:
        original = RemoteEventHandlerInvocation(element_id="b1", action="click")
        restored = RemoteEventHandlerInvocation.from_dict(original.to_dict())
        assert restored.element_id == "b1"
        assert restored.action == "click"

    def test_roundtrip_preserves_scene_id(self) -> None:
        original = RemoteEventHandlerInvocation(
            element_id="b1", action="click", scene_id="s1"
        )
        restored = RemoteEventHandlerInvocation.from_dict(original.to_dict())
        assert restored.scene_id == "s1"

    def test_registry_roundtrip(self) -> None:
        original = RemoteEventHandlerInvocation(
            element_id="b1", action="click", event_kind="button_clicked", scene_id="s1"
        )
        restored = message_from_dict(message_to_dict(original))
        assert restored == original

    def test_hub_token_never_crosses_the_wire(self) -> None:
        """W6: ``hub_token`` is the Display's own routing hint for a
        scene-less (menu) click, resolved before the send -- the Hub that
        receives this invocation already knows its own identity and must
        never see this field on the wire."""
        original = RemoteEventHandlerInvocation(
            element_id="voxd\x1fmusic", action="menu", hub_token="pembroke\x1f123"
        )

        d = original.to_dict()

        assert "hub_token" not in d

    def test_hub_token_defaults_to_none_on_decode(self) -> None:
        """A dict with no ``hub_token`` key (every real wire payload) decodes
        to ``None`` -- the field is never read back from the wire, so a
        sender could not smuggle a fake one through even if it tried."""
        d = {"type": "remote_invocation", "element_id": "m", "action": "menu"}

        restored = RemoteEventHandlerInvocation.from_dict(d)

        assert restored.hub_token is None

    def test_hub_token_is_ignored_even_if_present_in_the_payload(self) -> None:
        """Decode never reads ``hub_token`` from the wire dict at all -- a
        malicious or buggy sender including one has no effect."""
        d = {
            "type": "remote_invocation",
            "element_id": "m",
            "action": "menu",
            "hub_token": "spoofed\x1f1",
        }

        restored = RemoteEventHandlerInvocation.from_dict(d)

        assert restored.hub_token is None

    def test_registry_roundtrip_drops_hub_token(self) -> None:
        original = RemoteEventHandlerInvocation(
            element_id="m", action="menu", hub_token="pembroke\x1f123"
        )

        restored = message_from_dict(message_to_dict(original))

        assert isinstance(restored, RemoteEventHandlerInvocation)
        assert restored.hub_token is None
        assert restored != original  # the one field the wire never carries
