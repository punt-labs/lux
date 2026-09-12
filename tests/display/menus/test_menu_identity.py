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


_ZWSP = chr(0x200B)


class TestLabelContainingHashHash:
    """A human label that itself contains ``##`` is not split by the salt."""

    def test_same_hashhash_labels_render_without_conflict(self) -> None:
        items: list[dict[str, object]] = [
            {"label": "a##b", "id": "c1"},
            {"label": "a##b", "id": "c2"},
        ]
        imgui = FakeImGui(strict_ids=True)

        _clients_menu(items, hub=_HUB_A).render(imgui)  # no raise

        assert len(set(imgui.raw_ids_under("Clients"))) == 2

    def test_the_visible_text_keeps_both_hashes(self) -> None:
        # ImGui shows the text before the salt's ``##``; the ZWSP guards render
        # invisibly, so the user reads "a##b" rather than a truncated "a".
        menu = _clients_menu([{"label": "a##b", "id": "c1"}], hub=_HUB_A)
        imgui = FakeImGui()

        menu.render(imgui)

        (shown,) = imgui.labels_under("Clients")
        assert shown.replace(_ZWSP, "") == "a##b"


class TestLabelAccessors:
    """``label`` reports the human text, free of salt and ZWSP guards."""

    def test_menu_item_strips_salt_and_guard(self) -> None:
        salted = "a##b".replace("#", "#" + _ZWSP) + "##pembroke\x1f100:c1"
        assert MenuItem(salted, ignore).label == "a##b"

    def test_menu_item_plain_label_is_unchanged(self) -> None:
        assert MenuItem("Vox", ignore).label == "Vox"

    def test_submenu_reports_its_human_title(self) -> None:
        menu = _clients_menu([{"label": "x", "id": "c1"}], hub=_HUB_A)
        assert menu.label == "Clients"

    def test_submenu_title_with_hashhash(self) -> None:
        menu = Submenu.from_wire(
            checked_menu(wire_menu("a##b", [{"label": "x", "id": "c1"}])),
            _handlers(_HUB_A),
        )
        assert menu.label == "a##b"


class TestIdSuffixReset:
    """The id salt itself is guarded: a raw ``###`` in the id-part must not
    reset ImGui's id and drop the Hub token (the cross-Hub collision)."""

    def test_unguarded_hashhashhash_suffix_collides(self) -> None:
        # Fidelity control: ImGui's ``###`` resets the id to the text after it,
        # so an unguarded ``A###B`` id-part hashes to "B" on both Hubs.
        model = MenuModel(
            [
                Submenu(f"A##{_HUB_A.wire_token}:A###B", []),
                Submenu(f"A##{_HUB_B.wire_token}:A###B", []),
            ]
        )
        with pytest.raises(AssertionError, match="conflicting ImGui id"):
            model.render(FakeImGui(strict_ids=True))

    def test_submenu_hashhashhash_title_stays_hub_scoped(self) -> None:
        model = MenuModel(
            [
                Submenu.from_wire(
                    checked_menu(wire_menu("A###B", [{"label": "x", "id": "i"}])),
                    _handlers(_HUB_A),
                ),
                Submenu.from_wire(
                    checked_menu(wire_menu("A###B", [{"label": "x", "id": "i"}])),
                    _handlers(_HUB_B),
                ),
            ]
        )
        imgui = FakeImGui(strict_ids=True)

        model.render(imgui)  # no raise -- Hub token survives

        shown = {r.split("##", 1)[0].replace(_ZWSP, "") for r in imgui.raw_ids_under()}
        assert shown == {"A###B"}

    def test_leaf_hashhashhash_item_id_stays_hub_scoped(self) -> None:
        items: list[dict[str, object]] = [{"label": "Vox", "id": "a###b"}]
        one = _clients_menu(items, hub=_HUB_A)
        two = _clients_menu(items, hub=_HUB_B)
        a, b = FakeImGui(strict_ids=True), FakeImGui(strict_ids=True)

        one.render(a)  # no raise
        two.render(b)  # no raise

        assert a.raw_ids_under("Clients") != b.raw_ids_under("Clients")


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

    def test_two_sessions_same_labelled_top_menus_render_without_conflict(self) -> None:
        # The whb9 collision at the HEADING level, newly possible now the agent
        # bar aggregates many sessions: two sessions on ONE Hub both name a "Tools"
        # menu. The owner segment keeps their hidden identities distinct; without
        # it both salt to the same id and FakeImGui(strict) raises.
        model = MenuModel(
            [
                Submenu.from_wire(
                    checked_menu(
                        wire_menu("Tools", [{"label": "Run", "id": "a\x1frun"}], "a")
                    ),
                    _handlers(_HUB_A),
                ),
                Submenu.from_wire(
                    checked_menu(
                        wire_menu("Tools", [{"label": "Run", "id": "b\x1frun"}], "b")
                    ),
                    _handlers(_HUB_A),  # SAME Hub — only the owner differs
                ),
            ]
        )
        imgui = FakeImGui(strict_ids=True)

        model.render(imgui)  # no raise

        assert imgui.labels_under() == ("Tools", "Tools")  # labels verbatim
        assert len(set(imgui.raw_ids_under())) == 2  # distinct hidden identities


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
