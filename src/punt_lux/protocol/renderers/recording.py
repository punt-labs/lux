"""RecordingRenderer — appends a JSONL trace of render calls.

A test surface: the recording renderer lives under ``protocol/`` so
tests can use it without the ``[display]`` optional extra. Each render
call appends one JSON line; composites bracket their children with
begin/end entries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Self

from punt_lux.domain.element import Element

__all__ = ["RecordingLog", "RecordingRenderer", "RecordingRendererFactory"]


class RecordingLog:
    """Surface-shared state — one append-only JSONL file per recording run.

    The factory owns one log; per-kind renderers hold a reference and call
    ``append()``. The file is truncated on construction so each run is a
    fresh transcript.
    """

    _path: Path

    def __new__(cls, path: str | Path) -> Self:
        self = super().__new__(cls)
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            self._path.unlink()
        self._path.touch()
        return self

    @property
    def path(self) -> Path:
        """Return the file path the log writes to."""
        return self._path

    def append(self, entry: dict[str, object]) -> None:
        """Append one JSON entry as a single line to the log."""
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def lines(self) -> tuple[dict[str, object], ...]:
        """Return every recorded entry decoded back from JSON."""
        if not self._path.exists():
            return ()
        with self._path.open(encoding="utf-8") as fh:
            return tuple(json.loads(line) for line in fh if line.strip())


class RecordingRenderer:
    """Per-element renderer that records its lifecycle in a shared log.

    Carries the element's wire kind and id so the log entries identify
    which element produced each render/begin/end without the test
    having to track ordering separately.
    """

    _log: RecordingLog
    _kind: str
    _id: str

    def __new__(cls, log: RecordingLog, kind: str, elem_id: str) -> Self:
        self = super().__new__(cls)
        self._log = log
        self._kind = kind
        self._id = elem_id
        return self

    def render(self) -> None:
        """Record a leaf render."""
        self._log.append({"op": "render", "kind": self._kind, "id": self._id})

    def begin(self) -> None:
        """Record a composite begin."""
        self._log.append({"op": "begin", "kind": self._kind, "id": self._id})

    def end(self) -> None:
        """Record a composite end."""
        self._log.append({"op": "end", "kind": self._kind, "id": self._id})


class RecordingRendererFactory:
    """Factory that returns a RecordingRenderer for any ``Element``.

    Dispatches via ``isinstance(elem, Element)`` against the
    runtime-checkable domain Protocol (PY-TS-10): the Protocol already
    declares ``id`` and ``kind`` properties, so any conforming element
    satisfies the contract.
    """

    _log: RecordingLog

    def __new__(cls, log: RecordingLog) -> Self:
        self = super().__new__(cls)
        self._log = log
        return self

    @property
    def log(self) -> RecordingLog:
        """Return the underlying log for assertions after the render."""
        return self._log

    def __call__(self, elem: object) -> RecordingRenderer:
        if not isinstance(elem, Element):
            msg = (
                "RecordingRendererFactory requires an Element with 'id' "
                f"and 'kind' properties; got {type(elem).__name__}"
            )
            raise TypeError(msg)
        return RecordingRenderer(self._log, elem.kind, elem.id)
