"""Introspection-primitive tests — render_path + resolved_props.

Two layers:

- Unit: ``ElementInspection`` / ``SceneInspection`` classify a hand-built
  element and serialize the ``element_paths`` record.
- Integration: the enriched ``inspect_scene`` handler registered on a real
  ``DisplayServer`` is driven through ``QueryDispatcher.handle_query`` after a
  scene is fed through the real ``_handle_message`` path, so render_path and
  resolved_props are read from live display state — not a stub.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from punt_lux.display import DisplayServer
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    DialogElement,
    ProgressElement,
    TextElement,
)
from punt_lux.scene_inspection import ElementInspection, SceneInspection

if TYPE_CHECKING:
    from punt_lux.domain.inspectable import Inspectable
    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element


def _server() -> DisplayServer:
    """Construct a headless DisplayServer (no socket bind, no ImGui)."""
    return DisplayServer("/tmp/test-lux-inspect.sock")


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    return sock


def _feed(server: DisplayServer, elements: list[Element]) -> QueryResponse:
    """Push an all-native scene, then run the enriched inspect_scene query."""
    server._handle_message(_mock_sock(), SceneMessage(id="s1", elements=elements))
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


# -- unit: the typed records ------------------------------------------------


def test_element_inspection_reports_abc_render_path() -> None:
    rec = ElementInspection.from_element(
        TextElement(id="t1", content="hi"), domain_mirror_present=True
    ).to_dict()
    assert rec["render_path"] == "abc"
    assert rec["domain_mirror_present"] is True
    assert rec["props"] == {
        "content": "hi",
        "style": None,
        "tooltip": None,
        "color": "",
    }


def test_element_inspection_reports_legacy_render_path() -> None:
    """A not-yet-migrated dataclass kind reports ``legacy`` and its wire dict."""
    rec = ElementInspection.from_element(
        ProgressElement(id="p1", fraction=0.5), domain_mirror_present=False
    ).to_dict()
    assert rec["render_path"] == "legacy"
    # legacy fallback is the wire dict (defaults omitted by the codec)
    assert rec["props"] == {"kind": "progress", "id": "p1", "fraction": 0.5}


def test_scene_inspection_keeps_elements_array_and_adds_paths() -> None:
    inspection = SceneInspection.from_scene(
        "s1", [TextElement(id="t1", content="hi")], mirror_ids=frozenset({"t1"})
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
    ],
    ids=["text", "button", "checkbox", "dialog"],
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


def test_inspect_scene_reports_abc_for_migrated_and_legacy_for_the_rest() -> None:
    """render_path is ``abc`` for the 4 migrated kinds, ``legacy`` for progress."""
    server = _server()
    resp = _feed(
        server,
        [
            TextElement(id="t1", content="hi"),
            ButtonElement(id="b1", label="OK"),
            CheckboxElement(id="c1", label="Bold", value=True),
            DialogElement(id="d1", title="Confirm"),
            ProgressElement(id="p1", fraction=0.42),
        ],
    )
    assert _record(resp, "t1")["render_path"] == "abc"
    assert _record(resp, "b1")["render_path"] == "abc"
    assert _record(resp, "c1")["render_path"] == "abc"
    assert _record(resp, "d1")["render_path"] == "abc"
    assert _record(resp, "p1")["render_path"] == "legacy"


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


def test_inspect_scene_reports_domain_mirror_presence_for_native_scene() -> None:
    """An all-native scene routes into the display mirror — present is True."""
    server = _server()
    resp = _feed(
        server,
        [
            TextElement(id="t1", content="hi"),
            CheckboxElement(id="c1", label="Bold", value=True),
        ],
    )
    assert _record(resp, "t1")["domain_mirror_present"] is True
    assert _record(resp, "c1")["domain_mirror_present"] is True


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
    resp = server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "ghost"})
    assert resp.error is not None
    assert "ghost" in resp.error
    assert not resp.result
