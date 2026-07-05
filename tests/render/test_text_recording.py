"""TextElement renders through RecordingRenderer per the renderer contract.

Text is a leaf that uses every default step hook, so its ``render()``
skeleton drives only ``paint`` (``_begin``/``_end`` defaults do not touch
the renderer). The recording log captures one
``{"op": "paint", "kind": "text", "id": ...}`` entry — the leaf shape.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers import RecordingLog, RecordingRendererFactory


def _emit(_msg: object) -> None:
    """No-op emit for the leaf Text element."""


def test_text_element_render_emits_single_paint_entry() -> None:
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
        assert log.lines() == ({"op": "paint", "kind": "text", "id": "t1"},)
