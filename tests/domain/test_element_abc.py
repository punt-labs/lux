"""Element ABC — template-method render() walks children; leaves render directly.

Per docs/oo-refactor/pr3-v2.1-design.md §7(ii): the ABC's template method is
the contract the io-model element kinds inherit. Leaves call
``renderer.render()``; composites bracket their children with
``renderer.begin()`` / ``renderer.end()`` and recurse into each child's
own ``render()``.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.renderer import Renderer


class _RecordingRenderer:
    """Minimal Renderer that appends each lifecycle call to a shared log."""

    _log: list[str]
    _tag: str

    def __new__(cls, log: list[str], tag: str) -> Self:
        self = super().__new__(cls)
        self._log = log
        self._tag = tag
        return self

    def render(self) -> None:
        self._log.append(f"render:{self._tag}")

    def begin(self) -> None:
        self._log.append(f"begin:{self._tag}")

    def end(self) -> None:
        self._log.append(f"end:{self._tag}")


class _RecordingFactory:
    """Renderer factory that mints _RecordingRenderer instances per element."""

    _log: list[str]

    def __new__(cls, log: list[str]) -> Self:
        self = super().__new__(cls)
        self._log = log
        return self

    def __call__(self, elem: object) -> Renderer:
        tag = getattr(elem, "tag", "?")
        if not isinstance(tag, str):
            msg = f"element {type(elem).__name__} has non-str tag"
            raise TypeError(msg)
        return _RecordingRenderer(self._log, tag)


def _emit(_evt: object) -> None:
    """No-op emit channel for tests that never publish events."""


class _Leaf(Element):
    """Concrete leaf element — adds a ``tag`` field for log identification."""

    _tag: str

    def __new__(cls, *, factory: _RecordingFactory, tag: str) -> Self:
        self = super().__new__(cls, renderer_factory=factory, emit=_emit)
        self._tag = tag
        return self

    @property
    def id(self) -> str:
        return self._tag

    @property
    def tag(self) -> str:
        return self._tag


class _Composite(Element):
    """Concrete composite element — owns a tuple of child elements."""

    _tag: str
    _kids: tuple[Element, ...]

    def __new__(
        cls,
        *,
        factory: _RecordingFactory,
        tag: str,
        children: tuple[Element, ...],
    ) -> Self:
        self = super().__new__(cls, renderer_factory=factory, emit=_emit)
        self._tag = tag
        self._kids = children
        return self

    @property
    def id(self) -> str:
        return self._tag

    @property
    def tag(self) -> str:
        return self._tag

    def _children(self) -> tuple[Element, ...]:
        return self._kids


def test_leaf_render_calls_renderer_render() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log)
    leaf = _Leaf(factory=factory, tag="leaf")
    leaf.render()
    assert log == ["render:leaf"]


def test_composite_render_brackets_children_with_begin_and_end() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log)
    composite = _Composite(
        factory=factory,
        tag="parent",
        children=(_Leaf(factory=factory, tag="a"), _Leaf(factory=factory, tag="b")),
    )
    composite.render()
    assert log == ["begin:parent", "render:a", "render:b", "end:parent"]


def test_composite_with_no_children_renders_as_leaf() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log)
    composite = _Composite(factory=factory, tag="empty", children=())
    composite.render()
    assert log == ["render:empty"]
