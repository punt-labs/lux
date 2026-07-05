"""TextElement renders through RecordingRenderer per the renderer contract.

Text is a leaf that uses every default step hook, so its ``render()``
skeleton drives the renderer's full ``begin`` → ``paint`` → ``end`` lifecycle.
A leaf renderer's ``begin`` reports open and its ``end`` is a no-op, so the
pixels are leaf-shaped; the recording log captures the three lifecycle entries.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers import RecordingLog, RecordingRendererFactory


def _emit(_msg: object) -> None:
    """No-op emit for the leaf Text element."""


def test_text_element_render_emits_begin_paint_end() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-rec-") as raw_dir:
        log = RecordingLog(Path(raw_dir) / "text.jsonl")
        factory = RecordingRendererFactory(log)
        elem = TextElement(
            renderer_factory=factory,
            emit=_emit,
            id="t1",
            content="Hello",
        )
        elem.render()
        assert log.lines() == (
            {"op": "begin", "kind": "text", "id": "t1"},
            {"op": "paint", "kind": "text", "id": "t1"},
            {"op": "end", "kind": "text", "id": "t1", "opened": True},
        )
