"""DrawElementRenderer color parsing — hex strings and RGBA lists/tuples.

``_parse_color`` normalizes every color spelling the wire may carry to an
``(r, g, b, a)`` tuple, falling back to opaque white on anything malformed.
The paint methods themselves call into live ImGui and are covered by the
visual/e2e tiers; the pure parse is unit-tested here.
"""

from __future__ import annotations

from punt_lux.display.renderers.draw_element_renderer import DrawElementRenderer


class TestParseColor:
    def test_hex_rgb(self) -> None:
        assert DrawElementRenderer._parse_color("#FF8000") == (255, 128, 0, 255)

    def test_hex_rgba(self) -> None:
        assert DrawElementRenderer._parse_color("#FF800080") == (255, 128, 0, 128)

    def test_hex_no_hash(self) -> None:
        assert DrawElementRenderer._parse_color("FF8000") == (255, 128, 0, 255)

    def test_list_rgb(self) -> None:
        assert DrawElementRenderer._parse_color([70, 130, 230]) == (70, 130, 230, 255)

    def test_list_rgba(self) -> None:
        assert DrawElementRenderer._parse_color([70, 130, 230, 128]) == (
            70,
            130,
            230,
            128,
        )

    def test_tuple_rgba(self) -> None:
        assert DrawElementRenderer._parse_color((200, 80, 60, 255)) == (
            200,
            80,
            60,
            255,
        )

    def test_list_extra_components_ignored(self) -> None:
        result = DrawElementRenderer._parse_color([10, 20, 30, 40, 50, 60])
        assert result == (10, 20, 30, 40)

    def test_list_too_short_fallback(self) -> None:
        assert DrawElementRenderer._parse_color([10, 20]) == (255, 255, 255, 255)

    def test_empty_list_fallback(self) -> None:
        assert DrawElementRenderer._parse_color([]) == (255, 255, 255, 255)

    def test_list_non_numeric_fallback(self) -> None:
        assert DrawElementRenderer._parse_color(["x", "y", "z"]) == (255, 255, 255, 255)

    def test_list_none_elements_fallback(self) -> None:
        assert DrawElementRenderer._parse_color([None, None, None]) == (
            255,
            255,
            255,
            255,
        )

    def test_invalid_hex_fallback(self) -> None:
        assert DrawElementRenderer._parse_color("#ZZZZZZ") == (255, 255, 255, 255)

    def test_float_list_truncated_to_int(self) -> None:
        assert DrawElementRenderer._parse_color([70.9, 130.1, 230.5]) == (
            70,
            130,
            230,
            255,
        )

    def test_none_fallback(self) -> None:
        assert DrawElementRenderer._parse_color(None) == (255, 255, 255, 255)

    def test_int_fallback(self) -> None:
        assert DrawElementRenderer._parse_color(42) == (255, 255, 255, 255)
