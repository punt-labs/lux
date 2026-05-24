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

    SceneManager operates on the SceneMessage / Element union without
    per-kind branches for basics.  The guard checks three AST shapes:
    Name / Attribute references to the wire classes themselves AND
    Constant string nodes carrying the wire ``kind`` discriminators
    (e.g. ``elem.kind == "text"``).  All three forms would reintroduce
    a basics-specific branch in the SceneManager path.
    """
    import ast
    from pathlib import Path

    from punt_lux import scene

    source = (Path(scene.__file__).parent / "manager.py").read_text()
    tree = ast.parse(source)
    forbidden_classes = {
        "TextElement",
        "ImageElement",
        "SeparatorElement",
        "ProgressElement",
        "SpinnerElement",
        "MarkdownElement",
    }
    forbidden_kinds = {
        "text",
        "image",
        "separator",
        "progress",
        "spinner",
        "markdown",
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    class_hits = forbidden_classes & (names | attrs)
    kind_hits = forbidden_kinds & constants
    assert not class_hits, f"scene/manager.py references basics classes: {class_hits}"
    assert not kind_hits, f"scene/manager.py references basics kinds: {kind_hits}"


# -- SFH-NEW-1: wire-boundary type checks on basics from_dict --------------


def test_progress_rejects_non_numeric_fraction() -> None:
    """PY-EH-1: a wrong-typed fraction raises ValueError, not silent build."""
    import pytest

    with pytest.raises(ValueError, match=r"progress element.*'fraction'"):
        ProgressElement.from_dict({"id": "p1", "fraction": "not a float"})


def test_progress_rejects_bool_fraction() -> None:
    """PY-EH-1: bool is rejected (bool is-a int — easy to slip through)."""
    import pytest

    with pytest.raises(ValueError, match=r"progress element.*'fraction'"):
        ProgressElement.from_dict({"id": "p1", "fraction": True})


def test_progress_rejects_non_string_label() -> None:
    """PY-EH-1: optional fields are type-checked when present."""
    import pytest

    with pytest.raises(ValueError, match=r"progress element.*'label'"):
        ProgressElement.from_dict({"id": "p1", "fraction": 0.5, "label": 42})


def test_spinner_rejects_non_numeric_radius() -> None:
    import pytest

    with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
        SpinnerElement.from_dict({"id": "sp1", "radius": "big"})


def test_spinner_rejects_non_string_color() -> None:
    import pytest

    with pytest.raises(ValueError, match=r"spinner element.*'color'"):
        SpinnerElement.from_dict({"id": "sp1", "color": 0xFF})


def test_text_rejects_non_string_style() -> None:
    import pytest

    from punt_lux.protocol.elements.text_codec import JsonTextDecoder
    from punt_lux.protocol.renderers.null import NullRendererFactory

    def _emit(_msg: object) -> None:
        return None

    decoder = JsonTextDecoder(
        renderer_factory=NullRendererFactory(), emit=_emit, element_cls=TextElement
    )
    with pytest.raises(ValueError, match=r"text element.*'style'"):
        decoder.decode({"id": "t1", "content": "x", "style": 5})


def test_text_rejects_non_string_id() -> None:
    import pytest

    from punt_lux.protocol.elements.text_codec import JsonTextDecoder
    from punt_lux.protocol.renderers.null import NullRendererFactory

    def _emit(_msg: object) -> None:
        return None

    decoder = JsonTextDecoder(
        renderer_factory=NullRendererFactory(), emit=_emit, element_cls=TextElement
    )
    with pytest.raises(ValueError, match=r"text element.*'id'"):
        decoder.decode({"id": 7, "content": "x"})


def test_separator_rejects_non_string_id() -> None:
    import pytest

    with pytest.raises(ValueError, match=r"separator element.*'id'"):
        SeparatorElement.from_dict({"id": 99})


def test_image_rejects_non_int_width() -> None:
    import pytest

    with pytest.raises(ValueError, match=r"image element.*'width'"):
        ImageElement.from_dict({"id": "i1", "path": "/a.png", "width": "100"})


def test_image_rejects_non_string_path() -> None:
    import pytest

    with pytest.raises(ValueError, match=r"image element.*'path'"):
        ImageElement.from_dict({"id": "i1", "path": 7})


def test_markdown_rejects_non_string_content() -> None:
    import pytest

    with pytest.raises(ValueError, match=r"markdown element.*'content'"):
        MarkdownElement.from_dict({"id": "md1", "content": 42})


def test_element_from_dict_accepts_null_tooltip() -> None:
    """Copilot CP-5: ``{"tooltip": null}`` is equivalent to omitting the field."""
    payload = {"kind": "text", "id": "t1", "content": "hi", "tooltip": None}
    elem = element_from_dict(payload)
    assert isinstance(elem, TextElement)
    assert elem.tooltip is None


def test_element_from_dict_accepts_string_tooltip() -> None:
    payload = {"kind": "text", "id": "t1", "content": "hi", "tooltip": "hover me"}
    elem = element_from_dict(payload)
    assert isinstance(elem, TextElement)
    assert elem.tooltip == "hover me"


def test_element_from_dict_rejects_non_string_tooltip() -> None:
    """Copilot CP-5: non-str tooltips raise at the boundary (PY-EH-1)."""
    import pytest

    payload = {"kind": "text", "id": "t1", "content": "hi", "tooltip": 42}
    with pytest.raises(ValueError, match=r"text element.*'tooltip'"):
        element_from_dict(payload)


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
