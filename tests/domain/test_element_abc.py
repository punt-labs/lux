"""Element ABC — the fixed render() skeleton over four step hooks.

``render()`` runs ``_begin`` → ``_paint_self`` → ``_render_children`` →
``_end``. The defaults delegate to the renderer: ``_begin`` drives
``renderer.begin()``, ``_paint_self`` drives ``renderer.paint()``, ``_end``
drives ``renderer.end(opened=...)``. So every element drives its renderer's
full begin/paint/end lifecycle and no element overrides a step for the common
case — a leaf renderer's ``begin`` returns True and ``end`` is a no-op, a
container renderer opens and closes its surface. A component overrides a step
only to customise it (Open-Closed).
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
    """Concrete leaf — uses every default hook (drives begin/paint/end)."""

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
    """Plain composite — owns children, uses every default hook."""

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


class _BodylessComposite(_Composite):
    """Composite whose own body is only its children (overrides _paint_self)."""

    def _paint_self(self, renderer: Renderer) -> None:
        _ = renderer


def test_leaf_render_drives_renderer_begin_paint_end() -> None:
    log: list[str] = []
    _Leaf(factory=_RecordingFactory(log), tag="leaf").render()
    assert log == ["begin:leaf", "paint:leaf", "end:leaf:True"]


def test_composite_brackets_children_with_begin_and_end() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log)
    _Composite(
        factory=factory,
        tag="parent",
        children=(_Leaf(factory=factory, tag="a"), _Leaf(factory=factory, tag="b")),
    ).render()
    assert log == [
        "begin:parent",
        "paint:parent",
        "begin:a",
        "paint:a",
        "end:a:True",
        "begin:b",
        "paint:b",
        "end:b:True",
        "end:parent:True",
    ]


def test_composite_that_does_not_open_short_circuits_but_ends() -> None:
    log: list[str] = []
    factory = _RecordingFactory(log, opens=False)
    _Composite(
        factory=factory,
        tag="p",
        children=(_Leaf(factory=factory, tag="a"),),
    ).render()
    # begin returns False → no paint, no children — but end still runs.
    assert log == ["begin:p", "end:p:False"]


def test_step_override_customises_a_single_step() -> None:
    # Overriding _paint_self drops the parent's own body while the skeleton
    # and every other step keep the default (Open-Closed).
    log: list[str] = []
    factory = _RecordingFactory(log)
    _BodylessComposite(
        factory=factory,
        tag="p",
        children=(_Leaf(factory=factory, tag="a"),),
    ).render()
    assert log == ["begin:p", "begin:a", "paint:a", "end:a:True", "end:p:True"]


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
