"""A handler's writes stand together or not at all, and a broken rule is never logged.

The handler of a display interaction, and every observer its writes wake, write
under one transaction. A write the judge refuses, whichever of them made it, puts back
everything the others wrote, the state observers derive included, and is reported at
WARNING rather than taken for a handler that raised. A ``LockDisciplineError`` is a
bug in the code: it passes out of every fan-out on the interaction path.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.dial_reader import DialReader
from punt_lux.domain.hub.element_invocation_resolver import ResolvedInteraction
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
from punt_lux.domain.ids import ClientId, ElementId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.protocol import ReadyMessage, RemoteEventHandlerInvocation
from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.elements import ButtonElement, TableElement, TreeElement
from punt_lux.protocol.elements.slider import SliderElement
from tests.domain.display_double import Display
from tests.domain.test_nesting_cap_at_the_seam import _DEEP, _OWNER, _SCENE, _nodes
from tests.domain.test_retire_cause import _linked
from tests.link_access import drop_route, generation_of, reading_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.hub_display import HubDisplay


def _click() -> ButtonClicked:
    return ButtonClicked(
        scene_id=_SCENE, element_id=ElementId("b"), owner_id=ClientId("local")
    )


def _fire(store: HubDisplay, button: ButtonElement) -> None:
    with store.write_lock():
        ResolvedInteraction(
            element=button,
            owner=None,
            scene_id=_SCENE,
            store_guard=store.write_lock(),
        ).fire(_click(), store.write_seam.transaction())


def _scene(*roots: WireElement) -> HubDisplay:
    store = HubStoreFactory().display
    store.replace_scene(_OWNER, _SCENE, list(roots))
    return store


def _on_click(button: ButtonElement, handler: Callable[[ButtonClicked], None]) -> None:
    button.add_handler(ButtonClicked, handler)


def _too_deep(tree: TreeElement) -> None:
    tree.apply_patch({"nodes": [_nodes(_DEEP)]})


class TestAHandlerRefusedWhereverItWroteRollsBackEverything:
    def test_a_refused_observer_write_undoes_the_handlers_own(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        button = ButtonElement(id="b", label="x")
        table = TableElement(id="tb", columns=["c"], rows=[["r"]])
        deep = TreeElement(id="deep")
        store = _scene(button, table, deep)

        def observer(prop: str) -> None:
            if prop == "rows" and table.rows == (("s",),):
                _too_deep(deep)

        table.add_observer(observer)

        def handler(_event: ButtonClicked) -> None:
            table.apply_patch({"rows": [["s"]]})

        _on_click(button, handler)

        with caplog.at_level(logging.WARNING):
            _fire(store, button)

        assert (table.rows, deep.nodes) == ((("r",),), ())
        assert NestingCap.reason() in caplog.text
        assert "ButtonClicked" in caplog.text
        assert " b " in caplog.text

    def test_a_refusal_is_a_warning_not_a_handler_that_raised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        button = ButtonElement(id="b", label="x")
        deep = TreeElement(id="deep")
        store = _scene(button, deep)
        _on_click(button, lambda _e: _too_deep(deep))

        with caplog.at_level(logging.DEBUG):
            _fire(store, button)

        assert {r.levelno for r in caplog.records if "refused" in r.message} == {
            logging.WARNING
        }
        assert "handler raised" not in caplog.text

    def test_a_handlers_earlier_writes_are_undone_by_its_later_refusal(self) -> None:
        button = ButtonElement(id="b", label="x")
        shallow, deep = TreeElement(id="shallow"), TreeElement(id="deep")
        store = _scene(button, shallow, deep)

        def handler(_event: ButtonClicked) -> None:
            shallow.apply_patch({"nodes": [_nodes(2)]})
            _too_deep(deep)

        _on_click(button, handler)

        _fire(store, button)

        assert (shallow.nodes, deep.nodes) == ((), ())

    def test_the_state_a_handler_changes_in_a_model_is_restored_too(self) -> None:
        button = ButtonElement(id="b", label="x")
        rows = [["r1", "idle"], ["r2", "busy"], ["r3", "idle"]]
        table = TableElement(
            id="tb", columns=["id", "state"], rows=[list(r) for r in rows]
        )
        deep = TreeElement(id="deep")
        store = _scene(button, table, deep)
        model = FilteredTableModel(
            all_rows=tuple(tuple(r) for r in rows),
            key_column=0,
            search_columns=(1,),
            table=table,
        )

        def handler(_event: ButtonClicked) -> None:
            model.on_search("busy")
            _too_deep(deep)

        _on_click(button, handler)

        _fire(store, button)

        assert (table.rows, model.visible_ids()) == (
            tuple(tuple(r) for r in rows),
            frozenset({"r1", "r2", "r3"}),
        )

    def test_an_observer_of_a_slider_hears_its_value_restored(self) -> None:
        button = ButtonElement(id="b", label="x")
        slider = SliderElement(id="s", value=1.0)
        deep = TreeElement(id="deep")
        store = _scene(button, slider, deep)
        heard: list[float] = []
        slider.add_observer(lambda _prop: heard.append(slider.value))

        def handler(_event: ButtonClicked) -> None:
            slider.apply_patch({"value": 9.0})
            _too_deep(deep)

        _on_click(button, handler)

        _fire(store, button)

        assert (slider.value, heard[-1:]) == (1.0, [1.0])


class _Raises:
    def __call__(self, *_args: object) -> None:
        msg = "firing outside the lock"
        raise LockDisciplineError(msg)


class TestALockDisciplineErrorIsNeverSwallowed:
    def test_it_escapes_the_elements_fan_out(self) -> None:
        button = ButtonElement(id="b", label="x")
        button.add_handler(ButtonClicked, _Raises())

        with pytest.raises(LockDisciplineError):
            button.fire(_click())

    def test_it_escapes_the_interaction_handlers(self) -> None:
        handlers = InteractionHandlers()
        handlers.set_fallback(_Raises())
        msg = RemoteEventHandlerInvocation(element_id="b", action="b")

        with pytest.raises(LockDisciplineError):
            handlers.run(msg)

    def test_it_escapes_the_readers_route(self) -> None:
        d = Display()
        try:
            link = _linked(d, listening=False)
            generation = generation_of(link)
            hold = reading_of(link).claim_for_listener(drop_route, drop_route)
            assert hold is not None
            reader = DialReader(generation, hold.settler, _Raises(), threading.Event())

            with pytest.raises(LockDisciplineError):
                reader._routed_one(ReadyMessage())
        finally:
            d.close()
