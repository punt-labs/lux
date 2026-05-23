"""Renderer / RendererFactory / Decoder / Encoder Protocol structural checks.

Per docs/oo-refactor/pr3-v2.1-design.md §7(ii): the spike's four Protocols
are split across two production modules (``protocol/renderer.py`` for the
render-side trio, ``protocol/codec_protocols.py`` for the wire-side pair).
``runtime_checkable`` makes ``isinstance(obj, Protocol)`` valid; assert
that the built-in Null/Recording renderers structurally satisfy the
contracts they implement.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Self

from punt_lux.protocol.codec_protocols import Decoder, Encoder
from punt_lux.protocol.renderer import Renderer, RendererFactory
from punt_lux.protocol.renderers import (
    NullRenderer,
    NullRendererFactory,
    RecordingLog,
    RecordingRenderer,
    RecordingRendererFactory,
)


def test_null_renderer_satisfies_renderer_protocol() -> None:
    assert isinstance(NullRenderer(), Renderer)


def test_null_factory_satisfies_renderer_factory_protocol() -> None:
    assert isinstance(NullRendererFactory(), RendererFactory)


def test_recording_renderer_satisfies_renderer_protocol() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rp-") as raw_dir:
        log = RecordingLog(Path(raw_dir) / "trace.jsonl")
        assert isinstance(RecordingRenderer(log, "text", "t1"), Renderer)


def test_recording_factory_satisfies_renderer_factory_protocol() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rp-") as raw_dir:
        log = RecordingLog(Path(raw_dir) / "trace.jsonl")
        assert isinstance(RecordingRendererFactory(log), RendererFactory)


class _StubDecoder:
    """Minimal Decoder implementation for the structural-typing check."""

    def decode(self, raw: dict[str, object]) -> object:
        return raw


class _StubEncoder:
    """Minimal Encoder implementation for the structural-typing check."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, value: object) -> dict[str, object]:
        return {"value": value}


def test_stub_decoder_satisfies_decoder_protocol() -> None:
    assert isinstance(_StubDecoder(), Decoder)


def test_stub_encoder_satisfies_encoder_protocol() -> None:
    assert isinstance(_StubEncoder(), Encoder)
