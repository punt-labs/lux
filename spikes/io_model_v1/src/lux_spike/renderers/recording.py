"""RecordingRendererFactory — Display-tier surface that appends JSONL to a log.

Same Renderer Protocol as Text; different surface state (the log file)
and different per-kind renderers. Used to demonstrate that the io-model
supports multiple output surfaces without re-architecting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Self

from lux_spike.elements import ButtonElement, LabelElement, PanelElement

if TYPE_CHECKING:
    from lux_spike.element import Element


class RecordingLog:
    """Surface-shared state: appends one JSON line per render call.
    Held by the factory; passed to per-kind renderers via constructor."""

    _path: Path

    def __new__(cls, path: str | Path) -> Self:
        self = object.__new__(cls)
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            self._path.unlink()
        self._path.touch()
        return self

    def append(self, entry: dict[str, object]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    @property
    def path(self) -> Path:
        return self._path


class RecordingLabelRenderer:
    _elem: LabelElement
    _log: RecordingLog

    def __new__(cls, elem: LabelElement, log: RecordingLog) -> Self:
        self = object.__new__(cls)
        self._elem = elem
        self._log = log
        return self

    def render(self) -> None:
        self._log.append({"op": "render", "kind": "label", "id": self._elem.id, "content": self._elem.content})

    def begin(self) -> None:
        pass

    def end(self) -> None:
        pass


class RecordingButtonRenderer:
    _elem: ButtonElement
    _log: RecordingLog

    def __new__(cls, elem: ButtonElement, log: RecordingLog) -> Self:
        self = object.__new__(cls)
        self._elem = elem
        self._log = log
        return self

    def render(self) -> None:
        self._log.append({"op": "render", "kind": "button", "id": self._elem.id, "label": self._elem.label})

    def begin(self) -> None:
        pass

    def end(self) -> None:
        pass


class RecordingPanelRenderer:
    _elem: PanelElement
    _log: RecordingLog

    def __new__(cls, elem: PanelElement, log: RecordingLog) -> Self:
        self = object.__new__(cls)
        self._elem = elem
        self._log = log
        return self

    def render(self) -> None:
        pass

    def begin(self) -> None:
        self._log.append({"op": "begin", "kind": "panel", "id": self._elem.id})

    def end(self) -> None:
        self._log.append({"op": "end", "kind": "panel", "id": self._elem.id})


class RecordingRendererFactory:
    _log: RecordingLog

    def __new__(cls, log: RecordingLog) -> Self:
        self = object.__new__(cls)
        self._log = log
        return self

    def __call__(
        self, elem: Element
    ) -> RecordingLabelRenderer | RecordingButtonRenderer | RecordingPanelRenderer:
        match elem:
            case LabelElement():
                return RecordingLabelRenderer(elem, self._log)
            case ButtonElement():
                return RecordingButtonRenderer(elem, self._log)
            case PanelElement():
                return RecordingPanelRenderer(elem, self._log)
            case _:
                raise ValueError(f"recording surface has no renderer for {type(elem).__name__}")
