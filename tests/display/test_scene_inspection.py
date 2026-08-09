"""Introspection-primitive tests — resolved_props.

Two layers:

- Unit: ``ElementInspection`` / ``SceneInspection`` classify a hand-built
  element and serialize the ``element_paths`` record.
- Integration: the enriched ``inspect_scene`` handler registered on a real
  ``RenderLoop`` is driven through ``QueryRouter.handle_query`` after a
  scene is fed through the real ``_handle_message`` path, so resolved_props is
  read from live display state — not a stub.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from punt_lux.display import RenderLoop
from punt_lux.display.scene_inspection import ElementInspection, SceneInspection
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    DialogElement,
    PlotElement,
    ProgressElement,
    TableElement,
    TextElement,
)
from punt_lux.protocol.elements.plot_series import PlotSeries
from punt_lux.protocol.elements.tree import TreeElement

if TYPE_CHECKING:
    from punt_lux.domain.inspectable import Inspectable
    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element


def _server() -> RenderLoop:
    """Construct a headless RenderLoop (no socket bind, no ImGui)."""
    return RenderLoop("/tmp/test-lux-inspect.sock")


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    return sock


def _feed(server: RenderLoop, elements: list[Element]) -> QueryResponse:
    """Push an all-native scene, then run the enriched inspect_scene query."""
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=elements, frame_id="s1")
    )
    return server.query_router.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


# -- unit: the typed records ------------------------------------------------


def test_element_inspection_reports_resolved_props() -> None:
    rec = ElementInspection.from_element(TextElement(id="t1", content="hi")).to_dict()
    assert rec["id"] == "t1"
    assert rec["kind"] == "text"
    assert rec["props"] == {
        "content": "hi",
        "style": None,
        "tooltip": None,
        "color": "",
    }


def test_scene_inspection_keeps_elements_array_and_adds_paths() -> None:
    inspection = SceneInspection.from_scene(
        "s1", [TextElement(id="t1", content="hi")]
    ).to_dict()
    assert inspection["scene_id"] == "s1"
    assert inspection["elements"] == [{"kind": "text", "id": "t1", "content": "hi"}]
    paths = inspection["element_paths"]
    assert isinstance(paths, list)
    assert len(paths) == 1


# -- guardrail: resolved_props covers the settable surface ------------------

# Constructor params that are NOT element props: the DI sentinels the ABC
# injects and the identity field the inspection reports separately.
_NON_PROP_PARAMS = frozenset({"renderer_factory", "emit", "id"})


def _constructor_prop_fields(cls: type[Inspectable]) -> set[str]:
    """Return the keyword-only constructor params that are resolved props."""
    return {
        name
        for name, param in inspect.signature(cls).parameters.items()
        if param.kind is inspect.Parameter.KEYWORD_ONLY and name not in _NON_PROP_PARAMS
    }


def _setter_fields(cls: type[Inspectable]) -> set[str]:
    """Return the patch-settable fields, one per ``_set_<field>`` method."""
    return {n.removeprefix("_set_") for n in dir(cls) if n.startswith("_set_")}


@pytest.mark.parametrize(
    "element",
    [
        TextElement(id="t1", content="hi"),
        ButtonElement(id="b1"),
        CheckboxElement(id="c1"),
        DialogElement(id="d1"),
        TreeElement(id="tr1"),
        PlotElement(id="pl1"),
    ],
    ids=["text", "button", "checkbox", "dialog", "tree", "plot"],
)
def test_resolved_props_covers_the_settable_surface(element: Inspectable) -> None:
    """Every constructor/patch-settable field must appear in resolved_props.

    The keys are derived from the element's own constructor signature and
    ``_set_<field>`` methods — not a hardcoded list — so the guardrail keeps
    holding as new kinds copy the template. A kind that adds a settable field
    but forgets it in ``resolved_props`` fails here instead of passing every
    other gate. Derived-only props (dialog's ``visible``/``confirmed``) are
    allowed to exceed the settable surface; the check is coverage, not
    equality.
    """
    cls = type(element)
    settable = _constructor_prop_fields(cls) | _setter_fields(cls)
    resolved = set(element.resolved_props())
    missing = settable - resolved
    assert not missing, (
        f"{cls.__name__}.resolved_props() omits settable field(s): {sorted(missing)}"
    )


# -- integration: the live enriched handler ---------------------------------


def test_inspect_scene_records_every_kind() -> None:
    """Every kind produces an ``element_paths`` record keyed by id and kind."""
    server = _server()
    resp = _feed(
        server,
        [
            TextElement(id="t1", content="hi"),
            ButtonElement(id="b1", label="OK"),
            CheckboxElement(id="c1", label="Bold", value=True),
            DialogElement(id="d1", title="Confirm"),
            ProgressElement(id="p1", fraction=0.42),
            PlotElement(id="pl1", series=(PlotSeries("y", "line", (1.0,), (2.0,)),)),
            TableElement(id="tbl1", columns=["A"], rows=[["x"]]),
        ],
    )
    assert _record(resp, "t1")["kind"] == "text"
    assert _record(resp, "b1")["kind"] == "button"
    assert _record(resp, "c1")["kind"] == "checkbox"
    assert _record(resp, "d1")["kind"] == "dialog"
    assert _record(resp, "p1")["kind"] == "progress"
    assert _record(resp, "pl1")["kind"] == "plot"
    assert _record(resp, "tbl1")["kind"] == "table"


def test_inspect_scene_resolved_props_read_back_including_defaults() -> None:
    """resolved_props reports full state including fields the wire dict omits."""
    server = _server()
    resp = _feed(
        server,
        [
            TextElement(id="t1", content="hi"),
            CheckboxElement(id="c1", label="", value=False),
        ],
    )
    text_props = _record(resp, "t1")["props"]
    assert text_props == {"content": "hi", "style": None, "tooltip": None, "color": ""}

    # value=False and label="" are defaults the checkbox codec strips from the
    # wire dict; resolved_props must still report them.
    box_props = _record(resp, "c1")["props"]
    assert box_props == {"label": "", "value": False, "tooltip": None}


def test_inspect_scene_preserves_the_elements_array() -> None:
    """The enriched handler keeps the built-in ``elements`` list byte-for-byte."""
    server = _server()
    resp = _feed(server, [TextElement(id="t1", content="hi")])
    result = resp.result
    assert result is not None
    assert result["elements"] == [{"kind": "text", "id": "t1", "content": "hi"}]


def test_inspect_scene_unknown_scene_surfaces_error_not_empty() -> None:
    """A missing scene raises LookupError → QueryResponse.error, not a blank."""
    server = _server()
    resp = server.query_router.handle_query("inspect_scene", {"scene_id": "ghost"})
    assert resp.error is not None
    assert "ghost" in resp.error
    assert not resp.result
