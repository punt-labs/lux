"""RecordingRenderer + RecordingRendererFactory append JSONL traces.

The recording surface is the headless test fixture for the renderer
Protocol. Each render/begin/end appends one entry; the factory
dispatches by ``isinstance(elem, Element)`` against the
runtime-checkable domain Protocol (PY-TS-10 — no hasattr dispatch).
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import pytest

from punt_lux.protocol.renderers import (
    RecordingLog,
    RecordingRenderer,
    RecordingRendererFactory,
)


@dataclass(frozen=True, slots=True)
class _FakeElement:
    """Minimal element satisfying the domain ``Element`` Protocol."""

    id: str
    kind: str
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return the wire form — minimal id+kind suffices for the factory."""
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Reconstruct from ``to_dict`` output — symmetric with the encoder."""
        return cls(id=str(d["id"]), kind=str(d["kind"]))


def _log_path(tmp_dir: Path, name: str) -> Path:
    return tmp_dir / f"{name}.jsonl"


def test_recording_log_creates_empty_file_on_construction() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rec-") as raw_dir:
        path = _log_path(Path(raw_dir), "fresh")
        log = RecordingLog(path)
        assert log.path.exists()
        assert log.lines() == ()


def test_recording_renderer_render_appends_entry() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rec-") as raw_dir:
        log = RecordingLog(_log_path(Path(raw_dir), "render"))
        renderer = RecordingRenderer(log, "text", "t1")
        renderer.render()
        assert log.lines() == ({"op": "render", "kind": "text", "id": "t1"},)


def test_recording_renderer_begin_appends_entry() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rec-") as raw_dir:
        log = RecordingLog(_log_path(Path(raw_dir), "begin"))
        renderer = RecordingRenderer(log, "group", "g1")
        renderer.begin()
        assert log.lines() == ({"op": "begin", "kind": "group", "id": "g1"},)


def test_recording_renderer_end_appends_entry() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rec-") as raw_dir:
        log = RecordingLog(_log_path(Path(raw_dir), "end"))
        renderer = RecordingRenderer(log, "group", "g1")
        renderer.end()
        assert log.lines() == ({"op": "end", "kind": "group", "id": "g1"},)


def test_recording_renderer_factory_dispatches_by_kind_and_id() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rec-") as raw_dir:
        log = RecordingLog(_log_path(Path(raw_dir), "factory"))
        factory = RecordingRendererFactory(log)
        renderer = factory(_FakeElement(id="x", kind="text"))
        renderer.render()
        assert log.lines() == ({"op": "render", "kind": "text", "id": "x"},)


def test_recording_renderer_factory_raises_on_non_element() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rec-") as raw_dir:
        log = RecordingLog(_log_path(Path(raw_dir), "bad"))
        factory = RecordingRendererFactory(log)
        with pytest.raises(TypeError, match="requires an Element"):
            factory(object())
