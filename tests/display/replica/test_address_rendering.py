"""Unit tests for AddressRendering -- the Display's identity facade."""

from __future__ import annotations

from punt_lux.display.replica.address_rendering import AddressRendering
from punt_lux.display.replica.frame import Frame
from punt_lux.domain.hub_id import HubId
from punt_lux.domain.id_separator import ID_SEPARATOR

_PEMBROKE_1 = HubId("pembroke", 100)
_PEMBROKE_2 = HubId("pembroke", 200)
_OKINOS = HubId("okinos", 300)


def _rendering(*noted: tuple[HubId, str]) -> AddressRendering:
    """An AddressRendering with the given connections noted."""
    rendering = AddressRendering()
    for hub, key in noted:
        rendering.note_connection(hub, key)
    return rendering


def _frame(
    hub: HubId, frame_id: str, title: str, scope_label: str | None = None
) -> Frame:
    """A minimal on-screen frame owned by ``hub``, labelled if the Hub named it."""
    return Frame(
        hub=hub,
        frame_id=frame_id,
        title=title,
        owner_fds={1},
        scenes={},
        scene_order=[],
        scope_label=scope_label,
    )


class TestHiddenIdFor:
    def test_prepends_the_hub_wire_token_to_the_composed_key(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        hidden = rendering.hidden_id_for(_PEMBROKE_1, "frame-1")
        assert hidden == f"{_PEMBROKE_1.wire_token}{ID_SEPARATOR}frame-1"

    def test_namespaces_a_key_that_already_carries_the_separator(self) -> None:
        """A menu_id is a Rung-2 composed id and carries the separator; the Hub
        dimension is prepended, not rejected."""
        rendering = _rendering((_PEMBROKE_1, "c1"))
        menu_id = f"conn-7{ID_SEPARATOR}ticket-3"
        hidden = rendering.hidden_id_for(_PEMBROKE_1, menu_id)
        assert hidden == f"{_PEMBROKE_1.wire_token}{ID_SEPARATOR}{menu_id}"

    def test_two_hubs_minting_the_same_key_get_distinct_hidden_ids(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        first = rendering.hidden_id_for(_PEMBROKE_1, "vox")
        second = rendering.hidden_id_for(_PEMBROKE_2, "vox")
        assert first != second


class TestFrameTitle:
    """DES-100: the connection rung shows whenever the frame has a label."""

    def test_a_lone_labelled_frame_reads_label_then_title(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox", "lux")
        assert rendering.frame_title(frame) == "lux :: Vox"

    def test_two_sessions_of_one_repo_read_lux_and_lux_2(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        first = _frame(_PEMBROKE_1, "vox-1", "Vox", "lux")
        second = _frame(_PEMBROKE_1, "vox-2", "Vox", "lux (2)")
        assert rendering.frame_title(first) == "lux :: Vox"
        assert rendering.frame_title(second) == "lux (2) :: Vox"

    def test_two_applets_of_one_session_share_the_label(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        assert rendering.frame_title(_frame(_PEMBROKE_1, "b", "Beads", "lux")) == (
            "lux :: Beads"
        )
        assert rendering.frame_title(_frame(_PEMBROKE_1, "v", "Vox", "lux")) == (
            "lux :: Vox"
        )

    def test_an_unlabelled_frame_keeps_its_plain_title(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        assert rendering.frame_title(_frame(_PEMBROKE_1, "s", "Vox")) == "Vox"

    def test_with_no_connection_noted_a_frame_still_reads_plain(self) -> None:
        assert AddressRendering().frame_title(_frame(_PEMBROKE_1, "s", "Vox")) == "Vox"

    def test_two_hubs_prefix_the_hub_label_ahead_of_the_scope_label(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_OKINOS, "c2"))
        labelled = _frame(_PEMBROKE_1, "vox", "Vox", "lux (2)")
        plain = _frame(_OKINOS, "vox", "Vox")
        assert rendering.frame_title(labelled) == "pembroke :: lux (2) :: Vox"
        assert rendering.frame_title(plain) == "okinos :: Vox"

    def test_two_hubs_minting_one_label_never_interact(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        one = _frame(_PEMBROKE_1, "vox", "Vox", "lux")
        two = _frame(_PEMBROKE_2, "vox", "Vox", "lux")
        assert rendering.frame_title(one) == "pembroke :: lux :: Vox"
        assert rendering.frame_title(two) == "pembroke (2) :: lux :: Vox"

    def test_a_departed_second_hub_returns_the_survivor_to_its_label_alone(
        self,
    ) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_OKINOS, "c2"))
        rendering.forget_connection(_OKINOS, "c2")
        frame = _frame(_PEMBROKE_1, "vox", "Vox", "lux")
        assert rendering.frame_title(frame) == "lux :: Vox"


class TestFrameProjection:
    def test_frame_title_disambiguates_two_hubs_same_title(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        one = _frame(_PEMBROKE_1, "vox", "Vox")
        two = _frame(_PEMBROKE_2, "vox", "Vox")
        assert rendering.frame_title(one) == "pembroke :: Vox"
        assert rendering.frame_title(two) == "pembroke (2) :: Vox"

    def test_a_lone_frame_keeps_its_plain_title(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        assert rendering.frame_title(_frame(_PEMBROKE_1, "vox", "Vox")) == "Vox"

    def test_frame_window_ids_differ_across_hubs_with_the_same_frame_id(
        self,
    ) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        one = _frame(_PEMBROKE_1, "vox", "Vox")
        two = _frame(_PEMBROKE_2, "vox", "Vox")
        assert rendering.frame_window_id(one) != rendering.frame_window_id(two)

    def test_frame_window_id_prepends_the_hub_to_the_frame_id(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox")
        assert (
            rendering.frame_window_id(frame)
            == f"{_PEMBROKE_1.wire_token}{ID_SEPARATOR}vox"
        )


class TestFrameWindowLabel:
    def test_is_the_visible_title_then_the_hidden_id(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox", "lux")
        assert rendering.frame_window_label(frame) == (
            f"lux :: Vox##{_PEMBROKE_1.wire_token}{ID_SEPARATOR}vox"
        )

    def test_a_label_arriving_changes_the_title_but_never_the_id_part(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox")
        before = rendering.frame_window_label(frame)

        frame.heading.relabel("lux")
        after = rendering.frame_window_label(frame)

        assert before.partition("##")[2] == after.partition("##")[2]
        assert before.partition("##")[0] == "Vox"
        assert after.partition("##")[0] == "lux :: Vox"


class TestWindowIdStabilityAcrossAmbiguity:
    """The visible title may change with Hub count; the ImGui window id may not.

    ImGui keys a window on the ``##``-suffix -- ``frame_window_id`` -- while the
    label before it (``frame_title``) is cosmetic. If the id shifted when a
    second Hub flipped a title from plain to prefixed, ImGui would see a new
    window and lose its position, scroll, and collapse state. The id derives
    only from ``frame.hub`` and ``frame.frame_id``; ambiguity never enters it.
    """

    def test_window_id_is_invariant_when_a_second_hub_changes_the_title(
        self,
    ) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox")
        id_before = rendering.frame_window_id(frame)
        title_before = rendering.frame_title(frame)

        rendering.note_connection(_PEMBROKE_2, "c2")  # a second same-host Hub

        assert rendering.frame_window_id(frame) == id_before  # identity holds
        assert title_before == "Vox"
        assert rendering.frame_title(frame) == "pembroke :: Vox"  # label moved

    def test_window_id_holds_when_the_second_hub_departs_again(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox")
        id_ambiguous = rendering.frame_window_id(frame)

        rendering.forget_connection(_PEMBROKE_2, "c2")

        assert rendering.frame_window_id(frame) == id_ambiguous
        assert rendering.frame_title(frame) == "Vox"  # re-elided to plain


class TestLifecycleRobustness:
    """The note/forget lifecycle tolerates the disconnect and reconnect paths."""

    def test_noting_the_same_connection_twice_leaves_one_live_hub(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        rendering.note_connection(_PEMBROKE_1, "c1")  # a redundant note
        assert rendering.frame_title(_frame(_PEMBROKE_1, "v", "Vox")) == "Vox"

    def test_forgetting_an_unnoted_connection_is_a_no_op(self) -> None:
        rendering = AddressRendering()
        rendering.forget_connection(_PEMBROKE_1, "never-noted")  # no raise
        assert rendering.frame_title(_frame(_PEMBROKE_1, "v", "Vox")) == "Vox"

    def test_a_departed_hubs_orphan_frame_still_renders(self) -> None:
        """An orphaned frame keeps ``frame.hub`` set to a Hub no longer live;
        the title path falls back to the plain label rather than failing."""
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox")
        rendering.forget_connection(_PEMBROKE_1, "c1")  # the Hub departs
        assert rendering.frame_title(frame) == "Vox"
        assert rendering.frame_window_id(frame).endswith("vox")


class TestADetailsFrameTitle:
    """The Hub titles a Details frame with the program; the Display qualifies it."""

    def test_a_lone_details_frame_reads_as_the_program(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "c1\x1flux.client-details.c1", "z-spec")

        assert rendering.frame_title(frame) == "z-spec"

    def test_across_hubs_the_hub_rung_is_added(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_OKINOS, "c2"))
        frame = _frame(_PEMBROKE_1, "c1\x1flux.client-details.c1", "z-spec")

        assert rendering.frame_title(frame) == "pembroke :: z-spec"
