"""A handler is all or nothing: its writes and removals stand together, or none do.

A confirm-and-dismiss dialog whose handler also updates its parent screen writes an
element and removes a root in one event. The removal is part of the handler's
transaction: it is carried out when everything the handler did stood, and a later
refusal, or a handler that raises, undoes the writes and the dismissal together. The
dialog's own model state goes back with the element, and the store and the element's
``removed`` flag never disagree.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple

import pytest

from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.ids import ElementId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.programmer_error import ProgrammerError
from punt_lux.protocol.elements import ButtonElement, TreeElement
from punt_lux.protocol.elements.dialog import DialogElement
from tests.domain.test_handler_writes_are_judged import _fire
from tests.domain.test_nesting_cap_at_the_seam import _DEEP, _OWNER, _SCENE, _nodes

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay


class _Screen(NamedTuple):
    store: HubDisplay
    button: ButtonElement
    status: TreeElement
    overloaded: TreeElement
    dialog: DialogElement


def _screen() -> _Screen:
    button = ButtonElement(id="b", label="x")
    status = TreeElement(id="status")
    overloaded = TreeElement(id="overloaded")
    dialog = DialogElement(id="d")
    store = HubStoreFactory().display
    store.replace_scene(_OWNER, _SCENE, [button, status, overloaded, dialog])
    return _Screen(store, button, status, overloaded, dialog)


def _is_installed(screen: _Screen) -> bool:
    return screen.store.write_seam.is_present(_SCENE, ElementId("d"))


def _untouched(screen: _Screen) -> bool:
    return (
        screen.status.label == ""
        and _is_installed(screen)
        and not screen.dialog.removed
        and screen.dialog.visible
        and not screen.dialog.confirmed
    )


class TestAHandlerThatWritesThenDismisses:
    def test_the_write_and_the_dismissal_both_stand(self) -> None:
        screen = _screen()

        def save_and_close(_event: ButtonClicked) -> None:
            screen.status.apply_patch({"label": "saved"})
            screen.dialog.model.confirm()

        screen.button.add_handler(ButtonClicked, save_and_close)

        _fire(screen.store, screen.button)

        assert screen.status.label == "saved"
        assert (screen.dialog.removed, screen.dialog.confirmed) == (True, True)
        assert not _is_installed(screen)

    def test_the_dismissal_waits_until_the_handler_has_stood(self) -> None:
        screen = _screen()
        seen: list[tuple[bool, bool]] = []

        def save_and_close(_event: ButtonClicked) -> None:
            screen.status.apply_patch({"label": "saved"})
            screen.dialog.model.confirm()
            seen.append((screen.dialog.removed, _is_installed(screen)))

        screen.button.add_handler(ButtonClicked, save_and_close)

        _fire(screen.store, screen.button)

        assert seen == [(False, True)]

    def test_a_removal_outside_a_transaction_is_immediate(self) -> None:
        screen = _screen()

        screen.dialog.mark_removed()

        assert (screen.dialog.removed, _is_installed(screen)) == (True, False)


class TestALaterRefusalUndoesTheWriteAndTheDismissalTogether:
    def test_the_screen_is_as_it_was(self, caplog: pytest.LogCaptureFixture) -> None:
        screen = _screen()

        def save_close_and_overload(_event: ButtonClicked) -> None:
            screen.status.apply_patch({"label": "saved"})
            screen.dialog.model.confirm()
            screen.overloaded.apply_patch({"nodes": [_nodes(_DEEP)]})  # refused

        screen.button.add_handler(ButtonClicked, save_close_and_overload)

        with caplog.at_level(logging.WARNING):
            _fire(screen.store, screen.button)

        assert _untouched(screen)
        assert screen.overloaded.nodes == ()
        assert "refused a write" in caplog.text
        assert "removals were rolled back" in caplog.text

    def test_a_dismissal_after_the_write_does_not_make_the_write_unheld(self) -> None:
        screen = _screen()

        def write_the_dialogs_own_title_then_close(_event: ButtonClicked) -> None:
            screen.dialog.apply_patch({"title": "bye"})
            screen.dialog.model.close()

        screen.button.add_handler(ButtonClicked, write_the_dialogs_own_title_then_close)

        _fire(screen.store, screen.button)

        assert (screen.dialog.title, screen.dialog.removed) == ("bye", True)
        assert not _is_installed(screen)


class TestAHandlerThatRaisesLeavesNothingApplied:
    def test_its_writes_and_its_dismissal_are_undone_and_it_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        screen = _screen()

        def save_close_and_fail(_event: ButtonClicked) -> None:
            screen.status.apply_patch({"label": "saved"})
            screen.dialog.model.confirm()
            raise KeyError("boom")

        screen.button.add_handler(ButtonClicked, save_close_and_fail)

        with caplog.at_level(logging.ERROR):
            _fire(screen.store, screen.button)

        assert _untouched(screen)
        (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
        message = record.getMessage()
        assert "save_close_and_fail" in message
        assert "ButtonClicked" in message
        assert "element b" in message
        assert record.exc_info is not None
        assert record.exc_info[1] is not None
        assert isinstance(record.exc_info[1].__cause__, KeyError)

    def test_the_writes_of_a_handler_that_ran_before_it_go_too(self) -> None:
        screen = _screen()

        def writes(_event: ButtonClicked) -> None:
            screen.status.apply_patch({"label": "saved"})

        def fails(_event: ButtonClicked) -> None:
            raise ValueError("second handler failed")

        screen.button.add_handler(ButtonClicked, writes)
        screen.button.add_handler(ButtonClicked, fails)

        _fire(screen.store, screen.button)

        assert screen.status.label == ""

    def test_a_programmer_error_propagates_once_the_undo_is_done(self) -> None:
        screen = _screen()

        def breaks_a_rule(_event: ButtonClicked) -> None:
            screen.status.apply_patch({"label": "saved"})
            screen.dialog.model.confirm()
            raise ProgrammerError("a rule the code keeps")

        screen.button.add_handler(ButtonClicked, breaks_a_rule)

        with pytest.raises(ProgrammerError, match="a rule the code keeps"):
            _fire(screen.store, screen.button)

        assert _untouched(screen)

    def test_a_remaining_handler_does_not_run_once_one_has_failed(self) -> None:
        screen = _screen()
        ran: list[str] = []

        def fails(_event: ButtonClicked) -> None:
            raise ValueError("first handler failed")

        def would_publish(_event: ButtonClicked) -> None:
            ran.append("second")

        screen.button.add_handler(ButtonClicked, fails)
        screen.button.add_handler(ButtonClicked, would_publish)

        _fire(screen.store, screen.button)

        assert ran == []


class TestATransactionOpenedInsideOneJoinsIt:
    def test_the_inner_write_falls_with_the_outer_transaction(self) -> None:
        screen = _screen()

        def inner_then_overload(_event: ButtonClicked) -> None:
            screen.store.write_seam.set_property(
                _SCENE, ElementId("status"), "label", "inner"
            )
            screen.overloaded.apply_patch({"nodes": [_nodes(_DEEP)]})  # refused

        screen.button.add_handler(ButtonClicked, inner_then_overload)

        _fire(screen.store, screen.button)

        assert screen.status.label == ""

    def test_the_inner_write_stands_with_the_outer_transaction(self) -> None:
        screen = _screen()

        def inner(_event: ButtonClicked) -> None:
            screen.store.write_seam.set_property(
                _SCENE, ElementId("status"), "label", "inner"
            )

        screen.button.add_handler(ButtonClicked, inner)

        _fire(screen.store, screen.button)

        assert screen.status.label == "inner"
