"""TextElement renders through RecordingRenderer per the renderer contract.

When a Text element is constructed with a ``RecordingRendererFactory``
and its template-method ``render()`` is invoked, the recording log
captures one ``{"op": "render", "kind": "text", "id": ...}`` entry — the
leaf shape.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers import RecordingLog, RecordingRendererFactory


def _emit(_msg: object) -> None:
    """No-op emit for the leaf Text element."""


def test_text_element_render_emits_single_leaf_entry() -> None:
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
        assert log.lines() == ({"op": "render", "kind": "text", "id": "t1"},)
