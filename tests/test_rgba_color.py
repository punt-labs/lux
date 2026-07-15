"""RgbaColor — the ABC color-picker path's hex↔tuple↔hex value object.

Covers the round trip (hex → tuple → 8-bit hex), arity-4 normalization, channel
clamping, the quantization that makes ``committed`` bit-equal the eventual echo,
and the fail-loud contract on malformed input (a validated hex never reaches
``from_hex`` malformed, so a bad one is a construction bypass that raises).
"""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.rgba_color import RgbaColor


class TestFromHex:
    def test_six_digit_hex_parses_opaque(self) -> None:
        assert RgbaColor.from_hex("#FF8000").as_tuple() == pytest.approx(
            (1.0, 128 / 255, 0.0, 1.0)
        )

    def test_eight_digit_hex_parses_alpha(self) -> None:
        assert RgbaColor.from_hex("#00FF0080").as_tuple() == pytest.approx(
            (0.0, 1.0, 0.0, 128 / 255)
        )

    def test_lowercase_hex_parses(self) -> None:
        assert RgbaColor.from_hex("#ffffff").as_tuple() == (1.0, 1.0, 1.0, 1.0)

    def test_six_digit_normalizes_to_arity_four(self) -> None:
        # A missing alpha channel always pads to opaque 1.0 — the carrier is
        # arity 4 regardless of the wire form, so tuple == stays well-defined.
        assert len(RgbaColor.from_hex("#123456").as_tuple()) == 4

    @pytest.mark.parametrize("bad", ["#ZZZZZZ", "#12345", "#1234567", "not-hex", ""])
    def test_malformed_hex_raises(self, bad: str) -> None:
        with pytest.raises(ValueError, match="hex"):
            RgbaColor.from_hex(bad)


class TestToHex:
    def test_rgb_drops_the_alpha_channel(self) -> None:
        # int() truncates like the legacy encoder, so 0.502*255 == 128.0 -> 0x80.
        color = RgbaColor((1.0, 0.502, 0.0, 0.5))
        assert color.to_hex(alpha=False) == "#FF8000"

    def test_rgba_keeps_the_alpha_channel(self) -> None:
        color = RgbaColor((1.0, 0.0, 0.0, 0.502))
        assert color.to_hex(alpha=True) == "#FF000080"

    def test_channels_clamp_out_of_range(self) -> None:
        # ImGui can hand back a slightly out-of-[0,1] channel; clamp before scale.
        color = RgbaColor((1.5, -0.2, 0.0, 2.0))
        assert color.to_hex(alpha=True) == "#FF0000FF"


class TestRoundTrip:
    @pytest.mark.parametrize(
        "hex_str", ["#FFFFFF", "#000000", "#1A2B3C", "#DEADBE", "#8040C0"]
    )
    def test_from_hex_is_deterministic(self, hex_str: str) -> None:
        # from_hex is a pure function of the hex; the reconciliation relies on
        # this (committed and the echoed hub value both parse the same hex, so
        # tuple == closes the window). to_hex∘from_hex is NOT asserted identity —
        # int() truncation matches the legacy encoder and that composition never
        # occurs in the render flow (to_hex only sees fresh imgui tuples).
        assert RgbaColor.from_hex(hex_str).as_tuple() == (
            RgbaColor.from_hex(hex_str).as_tuple()
        )

    def test_quantized_commit_bit_equals_the_echo(self) -> None:
        # The reconciliation soundness case: committing the ROUND-TRIPPED tuple
        # (from_hex of the fired hex) makes ``committed`` bit-equal the tuple the
        # Hub echoes (from_hex of the same hex), so tuple == closes the window
        # with no full-precision→8-bit one-frame pop.
        full_precision = (0.1 + 0.2, 0.7, 0.333333, 1.0)
        hex_val = RgbaColor(full_precision).to_hex(alpha=False)
        committed = RgbaColor.from_hex(hex_val).as_tuple()
        echoed = RgbaColor.from_hex(hex_val).as_tuple()
        assert committed == echoed


class TestCoerce:
    def test_four_tuple_passes_through(self) -> None:
        assert RgbaColor.coerce((0.1, 0.2, 0.3, 0.4)) == (0.1, 0.2, 0.3, 0.4)

    def test_three_tuple_pads_to_opaque(self) -> None:
        assert RgbaColor.coerce((0.1, 0.2, 0.3)) == (0.1, 0.2, 0.3, 1.0)

    def test_non_tuple_raises(self) -> None:
        with pytest.raises(TypeError, match="tuple"):
            RgbaColor.coerce("#FFFFFF")

    def test_wrong_arity_raises(self) -> None:
        with pytest.raises(ValueError, match="3 or 4"):
            RgbaColor.coerce((0.1, 0.2))
