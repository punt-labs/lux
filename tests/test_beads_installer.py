"""Unit tests for BeadsBoardInstaller — a rejected board is loud, not silent."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_installer import BeadsBoardInstaller
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.operations import RenderRequest, Scope

from .rest._fakes import ForbiddenPort, make_facade

if TYPE_CHECKING:
    import pytest

_SCOPE = Scope(ConnectionId("app-beads"))


def test_a_rejected_board_is_logged_and_shows_a_failure_scene(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The Hub rejects a scene with a duplicate element id as an OpError value.
    # The installer must not drop it silently: it logs the reason and installs a
    # visible red failure scene in the board's place.
    store = HubDisplay()
    monkeypatch.setattr(
        "punt_lux.tools.tools.OPERATIONS",
        make_facade(display_port=ForbiddenPort(), store=store),
    )
    board = BeadsBoard("beads-test", "Beads: test")
    dup: dict[str, object] = {"kind": "text", "id": "x", "content": "a"}
    rejected = RenderRequest(scene_id="beads-test", elements=[dup, dup])

    with caplog.at_level(logging.ERROR, logger="punt_lux.apps.beads_installer"):
        BeadsBoardInstaller.install(board, rejected, _SCOPE)

    assert "beads board rejected" in caplog.text
    # The red failure scene was installed in place of the dropped board.
    failure = store.resolve(SceneId("beads-test"), ElementId("beads-error"))
    assert failure is not None


def test_an_accepted_board_installs_without_a_failure_scene(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A well-formed board installs cleanly: nothing logged, no failure element.
    store = HubDisplay()
    monkeypatch.setattr(
        "punt_lux.tools.tools.OPERATIONS",
        make_facade(display_port=ForbiddenPort(), store=store),
    )
    board = BeadsBoard("beads-ok", "Beads: ok")
    element: dict[str, object] = {"kind": "text", "id": "only", "content": "hi"}
    good = RenderRequest(scene_id="beads-ok", elements=[element])

    with caplog.at_level(logging.ERROR, logger="punt_lux.apps.beads_installer"):
        BeadsBoardInstaller.install(board, good, _SCOPE)

    # Nothing logged means the failure path never ran, so no failure scene was
    # installed; the board's own element is present.
    assert caplog.text == ""
    assert store.resolve(SceneId("beads-ok"), ElementId("only")) is not None
