"""Wire-path tests: basics elements flow through Display.apply unchanged.

Each commit in the basics migration adds one class to the matrix below.
Per the migration plan, every kind must satisfy:

1. ``isinstance(elem, Element)`` is True against the domain Protocol.
2. ``element_from_dict({...})`` returns the typed class with no helpers.
3. ``Display.apply(client, AddElement(scene, elem))`` returns ElementAdded
   and the snapshot reflects the element.
4. Wire round-trip: ``element_to_dict(elem)`` produces byte-identical
   output to the pre-migration codec (asserted by make snapshot-parity).

Commit 4 covers TextElement; commits 5-9 add Image, Separator, Progress,
Spinner, Markdown.
"""

from __future__ import annotations

from punt_lux.domain import ElementId, SceneId
from punt_lux.domain.display import Display
from punt_lux.domain.element import Element
from punt_lux.domain.event import ElementAdded
from punt_lux.domain.update import AddElement
from punt_lux.protocol import (
    ImageElement,
    MarkdownElement,
    ProgressElement,
    SeparatorElement,
    SpinnerElement,
    TextElement,
    element_from_dict,
    element_to_dict,
)


def test_text_element_satisfies_element_protocol() -> None:
    elem = TextElement(id="t1", content="hello")
    assert isinstance(elem, Element)


def test_text_element_to_dict_strips_absent_optionals() -> None:
    elem = TextElement(id="t1", content="hello")
    # absent style and color are dropped to match the pre-migration wire shape.
    assert element_to_dict(elem) == {
        "id": "t1",
        "kind": "text",
        "content": "hello",
    }


def test_text_element_to_dict_emits_style_and_color_when_set() -> None:
    elem = TextElement(id="t1", content="hi", style="heading", color="#FF0000")
    assert element_to_dict(elem) == {
        "id": "t1",
        "kind": "text",
        "content": "hi",
        "style": "heading",
        "color": "#FF0000",
    }


def test_text_element_to_dict_includes_tooltip_when_set() -> None:
    elem = TextElement(id="t1", content="hi", tooltip="hover help")
    payload = element_to_dict(elem)
    assert payload["tooltip"] == "hover help"


def test_text_element_from_dict_round_trips_via_class_method() -> None:
    payload = {
        "kind": "text",
        "id": "t1",
        "content": "hello",
        "style": "caption",
        "color": "#888888",
    }
    elem = element_from_dict(payload)
    assert isinstance(elem, TextElement)
    assert elem.id == "t1"
    assert elem.content == "hello"
    assert elem.style == "caption"
    assert elem.color == "#888888"


def test_text_element_from_dict_accepts_arbitrary_style_string() -> None:
    """PR 1 keeps ``style: str | None`` to preserve wire shape (deferred tighten).

    The renderer treats unknown styles as falling back to default body styling,
    so accepting any string here is byte-compatible with the pre-migration codec.
    """
    payload = {"kind": "text", "id": "t1", "content": "hi", "style": "fancy"}
    elem = element_from_dict(payload)
    assert isinstance(elem, TextElement)
    assert elem.style == "fancy"


def test_text_element_wire_path_through_display_apply() -> None:
    """Wire-decoded TextElement reaches Display.apply and emits ElementAdded."""
    display = Display()
    client = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))

    wire = {"kind": "text", "id": "t1", "content": "hello"}
    elem = element_from_dict(wire)
    assert isinstance(elem, TextElement)

    result = display.apply(client, AddElement(scene_id=SceneId("s1"), element=elem))
    assert isinstance(result, ElementAdded)
    assert result.element_id == ElementId("t1")

    snap = display.snapshot(SceneId("s1"))
    stored = snap.element(ElementId("t1"))
    assert isinstance(stored, TextElement)
    assert stored.content == "hello"


# -- per-kind end-to-end coverage for the remaining basics -----------------


def test_image_element_satisfies_protocol_and_round_trips() -> None:
    elem = ImageElement(id="i1", path="/tmp/a.png", width=10, height=20)
    assert isinstance(elem, Element)
    payload = element_to_dict(elem)
    assert payload["kind"] == "image"
    assert payload["path"] == "/tmp/a.png"
    restored = element_from_dict(payload)
    assert isinstance(restored, ImageElement)
    assert restored.width == 10


def test_image_element_requires_path_or_data() -> None:
    """PY-EH-1: validation at the boundary — __post_init__ enforces."""
    import pytest

    with pytest.raises(ValueError, match="requires either"):
        ImageElement(id="i1")


def test_separator_element_round_trip() -> None:
    elem = SeparatorElement(id="s1")
    assert isinstance(elem, Element)
    payload = element_to_dict(elem)
    assert payload == {"kind": "separator", "id": "s1"}
    restored = element_from_dict({"kind": "separator", "id": "s1"})
    assert isinstance(restored, SeparatorElement)
    assert restored.id == "s1"


def test_separator_element_anonymous_omits_id() -> None:
    elem = SeparatorElement()
    payload = element_to_dict(elem)
    assert payload == {"kind": "separator"}


def test_progress_element_round_trip() -> None:
    elem = ProgressElement(id="p1", fraction=0.42, label="Loading")
    assert isinstance(elem, Element)
    payload = element_to_dict(elem)
    assert payload["fraction"] == 0.42
    assert payload["label"] == "Loading"
    restored = element_from_dict(payload)
    assert isinstance(restored, ProgressElement)
    assert restored.fraction == 0.42


def test_spinner_element_round_trip() -> None:
    elem = SpinnerElement(id="sp1", label="Working", radius=20.0, color="#FF00FF")
    assert isinstance(elem, Element)
    payload = element_to_dict(elem)
    assert payload["radius"] == 20.0
    assert payload["color"] == "#FF00FF"
    restored = element_from_dict(payload)
    assert isinstance(restored, SpinnerElement)
    assert restored.color == "#FF00FF"


def test_markdown_element_round_trip() -> None:
    elem = MarkdownElement(id="md1", content="# Hi")
    assert isinstance(elem, Element)
    payload = element_to_dict(elem)
    assert payload == {"kind": "markdown", "id": "md1", "content": "# Hi"}
    restored = element_from_dict(payload)
    assert isinstance(restored, MarkdownElement)
    assert restored.content == "# Hi"


def test_every_basics_kind_flows_through_display_apply() -> None:
    """PY-RF-2: every new domain type has a production caller from day one."""
    display = Display()
    client = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))

    elements: list[Element] = [
        TextElement(id="t1", content="hi"),
        ImageElement(id="i1", path="/tmp/x.png"),
        SeparatorElement(id="sep1"),
        ProgressElement(id="pg1", fraction=0.5),
        SpinnerElement(id="sp1"),
        MarkdownElement(id="md1", content="# Hi"),
    ]
    for elem in elements:
        result = display.apply(client, AddElement(scene_id=SceneId("s1"), element=elem))
        assert isinstance(result, ElementAdded), elem

    snap = display.snapshot(SceneId("s1"))
    assert snap.element_ids == frozenset({ElementId(e.id) for e in elements})


def test_basics_module_holds_only_registration() -> None:
    """basics.py is now a thin registration shim, not a class container.

    Each kind lives in its own module — the only class basics defines is
    ``BasicsRegistry``, which wires the six per-kind codecs into the
    package-level ElementCodec at import time.
    """
    from punt_lux.protocol.elements import basics

    assert hasattr(basics, "BasicsRegistry")
    assert basics.__all__ == ["BasicsRegistry"]


def test_scene_manager_has_no_basics_branches() -> None:
    """Step 8 verification: scene/manager.py never references basics kinds.

    SceneManager already operates on the SceneMessage / Element union
    without per-kind branches for basics — the existing dispatch handles
    every kind uniformly via getattr.  This test pins the absence so
    future refactors do not accidentally reintroduce a basics-specific
    branch in the SceneManager path.
    """
    import ast
    from pathlib import Path

    from punt_lux import scene

    source = (Path(scene.__file__).parent / "manager.py").read_text()
    tree = ast.parse(source)
    forbidden = {
        "TextElement",
        "ImageElement",
        "SeparatorElement",
        "ProgressElement",
        "SpinnerElement",
        "MarkdownElement",
    }
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    intersection = forbidden & referenced
    assert not intersection, f"scene/manager.py references basics kinds: {intersection}"


def test_basics_codec_helpers_are_gone_from_every_per_kind_module() -> None:
    """PL-PP-1 + PY-OO-7: no module-level `_to_dict_*` / `_from_dict_*` survives.

    Walks each per-element module's AST and verifies it defines no top-level
    function whose name starts with ``_to_dict_`` or ``_from_dict_``.  This is
    the migration's structural promise: codec lives on the class, not next to it.
    """
    import ast
    from pathlib import Path

    from punt_lux.protocol import elements

    elements_dir = Path(elements.__file__).parent
    for kind in ("image", "text", "separator", "progress", "spinner", "markdown"):
        source = (elements_dir / f"{kind}.py").read_text()
        tree = ast.parse(source)
        top_level_funcs = [
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        ]
        bad = [
            name
            for name in top_level_funcs
            if name.startswith(("_to_dict_", "_from_dict_"))
        ]
        assert not bad, f"{kind}.py still has module-level codec helpers: {bad}"
