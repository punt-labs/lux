"""Unit tests: pure functions, data models, scene validation."""

from __future__ import annotations

from punt_lux import decode_frame, encode_frame


def test_encode_decode_roundtrip(simple_scene: dict[str, object]) -> None:
    """Encoding then decoding a scene produces the original data."""
    frame = encode_frame(simple_scene)
    decoded, remaining = decode_frame(frame)
    assert decoded == simple_scene
    assert remaining == b""


def test_encode_frame_structure(simple_scene: dict[str, object]) -> None:
    """Encoded frame has 4-byte length prefix followed by JSON."""
    import json
    import struct

    frame = encode_frame(simple_scene)
    length = struct.unpack("!I", frame[:4])[0]
    payload = json.loads(frame[4:])
    assert length == len(frame) - 4
    assert payload["type"] == "scene"
    assert payload["id"] == "test-scene-001"


def test_decode_frame_incomplete_header() -> None:
    """Decoding fewer than 4 bytes raises ValueError."""
    import pytest

    with pytest.raises(ValueError, match="Incomplete frame header"):
        decode_frame(b"\x00\x00")


def test_decode_frame_incomplete_payload() -> None:
    """Decoding with insufficient payload raises ValueError."""
    import struct

    import pytest

    # Header says 100 bytes, but only 10 bytes of payload
    frame = struct.pack("!I", 100) + b"x" * 10
    with pytest.raises(ValueError, match="Incomplete frame payload"):
        decode_frame(frame)


def test_scene_fixture_structure(simple_scene: dict[str, object]) -> None:
    """Simple scene fixture has required fields."""
    assert simple_scene["type"] == "scene"
    assert "id" in simple_scene
    assert "elements" in simple_scene
    elements = simple_scene["elements"]
    assert isinstance(elements, list)
    assert len(elements) == 1


def test_interactive_scene_has_controls(
    interactive_scene: dict[str, object],
) -> None:
    """Interactive scene fixture has multiple widget types."""
    elements = interactive_scene["elements"]
    assert isinstance(elements, list)
    kinds = {e["kind"] for e in elements if isinstance(e, dict)}
    assert "slider" in kinds
    assert "checkbox" in kinds
    assert "button" in kinds
