"""Element ABC — the fixed render() skeleton over four step hooks.

``render()`` runs ``_begin`` → ``_paint_self`` → ``_render_children`` →
``_end``. The defaults require no overrides: a leaf paints only itself; a
plain composite paints itself then recurses its children (no bracketing,
because the default ``_begin``/``_end`` do not drive the renderer). A
container overrides ``_begin``/``_end`` to open and close a surface and to
short-circuit the inner steps when it does not open.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.renderer import Renderer


class _RecordingRenderer:
    """Minimal Renderer that appends each step call to a shared log.

    ``begin`` reports ``_opens`` so a test can drive the short-circuit
    branch; ``paint`` and ``end`` record unconditionally.
    """

    _log: list[str]
    _tag: str
    _opens: bool

    def __new__(cls, log: list[str], tag: str, *, opens: bool = True) -> Self:
        self = super().__new__(cls)
        self._log = log
        self._tag = tag
        self._opens = opens
        return self

    def begin(self) -> bool:
        self._log.append(f"begin:{self._tag}")
        return self._opens

    def paint(self) -> None:
        self._log.append(f"paint:{self._tag}")

    def end(self, *, opened: bool) -> None:
        self._log.append(f"end:{self._tag}:{opened}")


class _RecordingFactory:
    """Renderer factory that mints _RecordingRenderer instances per element."""

    _log: list[str]
    _opens: bool

    def __new__(cls, log: list[str], *, opens: bool = True) -> Self:
        self = super().__new__(cls)
        self._log = log
        self._opens = opens
        return self

    def __call__(self, elem: object) -> Renderer:
        tag = getattr(elem, "tag", "?")
        if not isinstance(tag, str):
            msg = f"element {type(elem).__name__} has non-str tag"
            raise TypeError(msg)
        return _RecordingRenderer(self._log, tag, opens=self._opens)


def _emit(_evt: object) -> None:
    """No-op emit channel for tests that never publish events."""


class _Leaf(Element):
    """Concrete leaf — uses every default hook (paints only itself)."""

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


class _Composite(_Leaf):
    """Plain composite — owns children, uses the default (unbracketed) hooks."""

    _kids: tuple[Element, ...]

    def __new__(
        cls,
        *,
        factory: _RecordingFactory,
        tag: str,
        children: tuple[Element, ...],
    ) -> Self:
        self = super().__new__(cls, factory=factory, tag=tag)
        self._kids = children
        return self

    def _children(self) -> tuple[Element, ...]:
        return self._kids


class _Container(_Composite):
    """Container — overrides begin/end to open a surface (like the dialog)."""

    def _begin(self, renderer: Renderer) -> bool:
        return renderer.begin()

    def _end(self, renderer: Renderer, *, opened: bool) -> None:
        renderer.end(opened=opened)


def test_leaf_render_paints_only_itself() -> None:
    log: list[str] = []
    _Leaf(factory=_RecordingFactory(log), tag="leaf").render()
    assert log == ["paint:leaf"]


def test_plain_composite_paints_self_then_children_unbracketed() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log)
    _Composite(
        factory=factory,
        tag="parent",
        children=(_Leaf(factory=factory, tag="a"), _Leaf(factory=factory, tag="b")),
    ).render()
    assert log == ["paint:parent", "paint:a", "paint:b"]


def test_container_brackets_children_with_begin_and_end() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log)
    _Container(
        factory=factory,
        tag="p",
        children=(_Leaf(factory=factory, tag="a"),),
    ).render()
    assert log == ["begin:p", "paint:p", "paint:a", "end:p:True"]


def test_container_that_does_not_open_short_circuits_but_ends() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log, opens=False)
    _Container(
        factory=factory,
        tag="p",
        children=(_Leaf(factory=factory, tag="a"),),
    ).render()
    # begin returns False → no paint, no children — but end still runs.
    assert log == ["begin:p", "end:p:False"]


def test_abc_validate_default_returns_no_errors() -> None:
    leaf = _Leaf(factory=_RecordingFactory([]), tag="leaf")
    assert leaf.validate() == ()


def test_abc_child_elements_bridges_children_hook() -> None:
    factory = _RecordingFactory([])
    kids = (_Leaf(factory=factory, tag="a"), _Leaf(factory=factory, tag="b"))
    composite = _Composite(factory=factory, tag="parent", children=kids)
    assert composite.child_elements() == kids


def test_abc_leaf_child_elements_is_empty() -> None:
    leaf = _Leaf(factory=_RecordingFactory([]), tag="leaf")
    assert leaf.child_elements() == ()
