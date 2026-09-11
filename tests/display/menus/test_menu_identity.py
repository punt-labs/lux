"""Aggregated menu entries are ImGui-identified by ``(Hub, item id)``, not label.

Dear ImGui raises "N visible items with conflicting ID" when two widgets under
one scope share an id. The Display aggregates entries whose human labels collide
across sessions and Hubs; keying identity on ``(source-Hub, Hub item id)`` after
``##`` keeps them distinct while the user still reads the plain label. These
tests drive the real ``Submenu.from_wire`` / ``WindowsMenu`` render path through
a ``FakeImGui`` that reproduces the conflict in strict mode.
"""

from __future__ import annotations

import pytest

from punt_lux.display.menus import MenuItem, MenuModel, Submenu
from punt_lux.display.menus.menu_click import MenuHandlers
from punt_lux.display.menus.windows_menu import WindowsMenu
from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.domain.identity import HubId
from tests.menu_doubles import (
    FakeChrome,
    FakeImGui,
    checked_menu,
    ignore,
    make_frame,
    wire_menu,
)

_CLOSED = FrameVisibility.CLOSED

_HUB_A = HubId("pembroke", 100)
_HUB_B = HubId("okinos", 200)


def _handlers(hub: HubId) -> MenuHandlers:
    return MenuHandlers(ignore, ignore, hub)


def _clients_menu(items: list[dict[str, object]], *, hub: HubId) -> Submenu:
    return Submenu.from_wire(checked_menu(wire_menu("Clients", items)), _handlers(hub))


class TestConflictDetectorFidelity:
    """The strict double must reproduce the very bug the fix closes."""

    def test_two_same_labelled_unsalted_items_collide(self) -> None:
        # The pre-fix behaviour: the label alone is the ImGui id.
        menu = Submenu("Clients", [MenuItem("Vox", ignore), MenuItem("Vox", ignore)])
        with pytest.raises(AssertionError, match="conflicting ImGui id"):
            menu.render(FakeImGui(strict_ids=True))

    def test_distinct_salts_under_one_menu_do_not_collide(self) -> None:
        menu = Submenu(
            "Clients",
            [MenuItem("Vox##a", ignore), MenuItem("Vox##b", ignore)],
        )
        imgui = FakeImGui(strict_ids=True)

        menu.render(imgui)  # no raise

        assert imgui.labels_under("Clients") == ("Vox", "Vox")
        assert len(set(imgui.raw_ids_under("Clients"))) == 2


class TestReplicatedLeafIdentity:
    """Leaves under one menu carry the item id in their ImGui salt."""

    def test_four_same_labelled_sessions_render_without_conflict(self) -> None:
        items: list[dict[str, object]] = [
            {"label": "Vox", "id": f"conn{n}\x1fopen"} for n in range(4)
        ]
        menu = _clients_menu(items, hub=_HUB_A)
        imgui = FakeImGui(strict_ids=True)

        menu.render(imgui)  # no raise

        assert imgui.labels_under("Clients") == ("Vox", "Vox", "Vox", "Vox")
        assert len(set(imgui.raw_ids_under("Clients"))) == 4

    def test_the_visible_label_stays_the_human_label(self) -> None:
        menu = _clients_menu([{"label": "Vox", "id": "conn\x1fopen"}], hub=_HUB_A)
        imgui = FakeImGui()

        menu.render(imgui)

        assert imgui.line("Vox").label == "Vox"

    def test_same_item_id_across_hubs_yields_distinct_identities(self) -> None:
        one = _clients_menu([{"label": "Vox", "id": "music"}], hub=_HUB_A)
        two = _clients_menu([{"label": "Vox", "id": "music"}], hub=_HUB_B)
        a, b = FakeImGui(), FakeImGui()

        one.render(a)
        two.render(b)

        assert a.raw_ids_under("Clients") != b.raw_ids_under("Clients")


class TestSubmenuContainerIdentity:
    """Two Hubs' same-named menus never collide at their shared scope."""

    def test_two_hubs_same_labelled_top_menus_render_without_conflict(self) -> None:
        model = MenuModel(
            [
                Submenu.from_wire(
                    checked_menu(wire_menu("voxd", [{"label": "Vox", "id": "m"}])),
                    _handlers(_HUB_A),
                ),
                Submenu.from_wire(
                    checked_menu(wire_menu("voxd", [{"label": "Vox", "id": "m"}])),
                    _handlers(_HUB_B),
                ),
            ]
        )
        imgui = FakeImGui(strict_ids=True)

        model.render(imgui)  # no raise

        assert imgui.labels_under() == ("voxd", "voxd")
        assert len(set(imgui.raw_ids_under())) == 2


class TestWindowsMenuReopenIdentity:
    """Closed frames sharing a title stay distinct in the Windows menu."""

    def _windows(self, frames: dict[str, Frame]) -> WindowsMenu:
        return WindowsMenu(
            get_frames=lambda: frames,
            on_clear_all=ignore,
            on_fit_all=ignore,
            on_raise_frame=ignore,
            chrome=FakeChrome(),
        )

    def test_two_same_titled_frames_render_without_conflict(self) -> None:
        frames = {
            "f1": make_frame("f1", visibility=_CLOSED, title="Vox", hub=_HUB_A),
            "f2": make_frame("f2", visibility=_CLOSED, title="Vox", hub=_HUB_B),
        }
        imgui = FakeImGui(strict_ids=True)

        self._windows(frames).section().render(imgui)  # no raise

        reopen = [
            raw for raw in imgui.raw_ids_under("Windows") if raw.startswith("Vox")
        ]
        assert len(reopen) == 2
        assert len(set(reopen)) == 2

    def test_the_reopen_entry_reads_the_frame_title(self) -> None:
        frame = make_frame("f1", visibility=_CLOSED, title="Vox", hub=_HUB_A)
        imgui = FakeImGui()

        self._windows({"f1": frame}).section().render(imgui)

        assert imgui.line("Vox").label == "Vox"
