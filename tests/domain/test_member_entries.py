"""MemberEntries — what one connection contributes to its submenu."""

from __future__ import annotations

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.member_entries import MemberEntries
from punt_lux.domain.hub.menu_frames import MenuFrames
from punt_lux.domain.hub.named_sessions import NamedSession
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ConnectionId

_CONN = ConnectionId("c1")


class _Leg:
    def wake(self) -> None:
        """Nothing to deliver."""


def _member(name: str, *callbacks: SessionCallback) -> NamedSession:
    session = (
        ClientSession(0.0)
        .with_identity(ClientIdentity(kind="mcp-session", name=name, repo="/w/lux"))
        .attached(_Leg())
    )
    for callback in callbacks:
        session = session.with_callback(callback)
    return NamedSession(_CONN, "lux", session)


class TestABareConnection:
    def test_it_contributes_one_entry_named_for_its_program(self) -> None:
        (entry,) = MemberEntries(_member("claude")).actions()

        assert entry.label == "claude"
        assert CallbackInvocation.from_menu_id(entry.id).is_details

    def test_the_entry_names_the_frame_it_opens(self) -> None:
        (entry,) = MemberEntries(_member("claude")).actions()

        assert entry.frame_id == MenuFrames(_CONN).details


class TestAConnectionWithCommands:
    def test_it_contributes_its_commands_and_no_entry_for_itself(self) -> None:
        beads = SessionCallback(id="beads", label="Beads", frame_id="beads-lux")
        run = SessionCallback(id="run", label="Run")

        actions = MemberEntries(_member("claude", beads, run)).actions()

        assert [a.label for a in actions] == ["Beads", "Run"]
        assert [a.frame_id for a in actions] == [
            MenuFrames(_CONN).of(beads),
            None,
        ]
