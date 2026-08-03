"""CallbackMenu — the uniform ``Clients ▸ <client> ▸ <command>`` menu build.

One ``Clients`` menu holds one submenu per identified live client that has
callbacks, named by the roster, that client's commands as the leaves, and the
Hub's own ``Details`` at the foot. The rule is the same for every kind of client
and every count, and two clients are never merged. Unidentified clients and
clients with no callbacks contribute nothing, and each leaf id round-trips a
click to whoever owns it — the client, or the Hub for ``Details``.
"""

from __future__ import annotations

from typing import final

from punt_lux.domain.hub.callback_menu import CallbackMenu
from punt_lux.domain.hub.client_identity import ClientIdentity, ClientKind
from punt_lux.domain.hub.client_roster import ClientRoster
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuSeparator
from punt_lux.domain.hub.named_sessions import NamedSessions
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ConnectionId


@final
class _SilentLeg:
    """A listen leg stand-in: the menu needs a client to hold one, not to push."""

    def wake(self) -> None:
        """No delivery here — these tests are about what the bar shows."""


def _session(
    name: str,
    repo: str | None,
    *callbacks: SessionCallback,
    kind: ClientKind = "mcp-session",
) -> ClientSession:
    """Build an identified session holding a leg and the callbacks it registered.

    The leg comes first because taking the slot clears what its last occupant
    owned, and because an entry with no leg to push a click to cannot be held.
    """
    session = (
        ClientSession(0.0)
        .with_identity(ClientIdentity(kind=kind, name=name, repo=repo))
        .attached(_SilentLeg())
    )
    for callback in callbacks:
        session = session.with_callback(callback)
    return session


def _beads() -> SessionCallback:
    return SessionCallback(id="beads", label="Beads")


def _menus(*sessions: tuple[str, ClientSession], roster: ClientRoster | None = None):
    """Compose the menu for the given connections, in the order they connected.

    One read of the live clients, named — what the registry hands over from inside
    its lock. Passing a roster across calls makes several reads of one Hub.
    """
    live = {ConnectionId(name): session for name, session in sessions}
    return CallbackMenu.from_named(NamedSessions.over(live, roster or ClientRoster()))


def _clients_menu(menus: list[Menu]) -> Menu:
    """Return the one ``Clients`` menu, failing loudly when there is not one."""
    assert [menu.label for menu in menus] == ["Clients"]
    return menus[0]


def _labels_under(menu: Menu) -> list[str]:
    """Return the labels directly under *menu*, skipping the rule."""
    return [entry.label for entry in menu.items if not isinstance(entry, MenuSeparator)]


def _submenu(menus: list[Menu], label: str) -> Menu:
    """Return one client's submenu from under ``Clients``."""
    found = [
        entry
        for entry in _clients_menu(menus).items
        if isinstance(entry, Menu) and entry.label == label
    ]
    assert len(found) == 1, f"expected one {label!r} submenu, got {len(found)}"
    return found[0]


class TestTheClientsMenu:
    """Every client's commands sit under the one ``Clients`` menu."""

    def test_a_one_command_client_is_a_submenu_under_clients(self) -> None:
        conn = ConnectionId("lux")

        menus = _menus(("lux", _session("claude", "/w/lux", _beads())))

        client = _submenu(menus, "lux")
        assert _labels_under(client) == ["Beads", "Details"]
        assert client.items[0] == MenuAction(
            id=CallbackInvocation(conn, "beads").menu_id, label="Beads"
        )

    def test_a_many_command_client_has_the_same_shape(self) -> None:
        session = _session(
            "claude",
            "/w/lux",
            SessionCallback(id="beads", label="Beads"),
            SessionCallback(id="build", label="Build"),
        )

        menus = _menus(("lux", session))

        # One Clients menu, one submenu in it, several leaves — no flattening
        # and no count-dependent shape.
        assert len(_clients_menu(menus).items) == 1
        assert _labels_under(_submenu(menus, "lux")) == ["Beads", "Build", "Details"]

    def test_a_leaf_is_named_for_the_command_alone(self) -> None:
        """The hierarchy disambiguates, so the leaf label carries nothing else."""
        menus = _menus(("s", _session("lux · lux · #4b97", "/w/lux", _beads())))

        assert _labels_under(_submenu(menus, "lux")) == ["Beads", "Details"]

    def test_two_clients_are_two_submenus_under_the_one_menu(self) -> None:
        vox, lux = ConnectionId("vox"), ConnectionId("lux")

        menus = _menus(
            ("vox", _session("claude", "/w/vox", _beads())),
            ("lux", _session("claude", "/w/lux", _beads())),
        )

        assert _labels_under(_clients_menu(menus)) == ["lux", "vox"]
        # The leaf ids carry their own connection, so a click routes correctly.
        assert _submenu(menus, "lux").items[0] == MenuAction(
            id=CallbackInvocation(lux, "beads").menu_id, label="Beads"
        )
        assert _submenu(menus, "vox").items[0] == MenuAction(
            id=CallbackInvocation(vox, "beads").menu_id, label="Beads"
        )

    def test_submenus_are_ordered_by_label(self) -> None:
        menus = _menus(
            ("q", _session("claude", "/w/quarry", _beads())),
            ("l", _session("claude", "/w/lux", _beads())),
        )

        assert _labels_under(_clients_menu(menus)) == ["lux", "quarry"]

    def test_no_client_means_no_clients_menu(self) -> None:
        assert _menus() == []


class TestEveryKindIsAClient:
    """A daemon and a session are both clients and read the same way."""

    def test_a_machine_wide_daemon_sits_under_clients_like_any_other(self) -> None:
        voxd = _session(
            "voxd", None, SessionCallback(id="music", label="Music"), kind="app"
        )

        menus = _menus(("vox", voxd))

        assert _labels_under(_clients_menu(menus)) == ["voxd"]
        assert _labels_under(_submenu(menus, "voxd")) == ["Music", "Details"]

    def test_a_daemon_and_a_session_are_two_submenus_of_one_menu(self) -> None:
        """No species split: one menu, one rule, whatever kind a client is."""
        voxd = _session(
            "voxd", None, SessionCallback(id="music", label="Music"), kind="app"
        )

        menus = _menus(
            ("vox", voxd),
            ("lux", _session("lux · lux · #4b97", "/w/lux", _beads(), kind="applet")),
        )

        assert [menu.label for menu in menus] == ["Clients"]
        assert _labels_under(_clients_menu(menus)) == ["lux", "voxd"]


class TestWhatANameIs:
    """A client is called after the place it works, numbered when two collide."""

    def test_a_client_is_named_for_its_repository(self) -> None:
        """Not for its declared name, which carries a distinctness token."""
        menus = _menus(
            (
                "s",
                _session(
                    "lux · lux · #4b97", "/Users/someone/lux", _beads(), kind="applet"
                ),
            )
        )

        assert _labels_under(_clients_menu(menus)) == ["lux"]

    def test_a_client_with_no_repository_is_called_what_it_calls_itself(self) -> None:
        session = _session("lux-cli", None, _beads(), kind="cli")

        menus = _menus(("cli", session))

        assert _labels_under(_clients_menu(menus)) == ["lux-cli"]

    def test_a_client_working_at_the_root_is_called_what_it_calls_itself(self) -> None:
        """``/`` is absolute, so it is an accepted repo — and it has no basename.

        A blank label is one the Menu model refuses, so composing this client's
        submenu raised where the bar is built.
        """
        menus = _menus(("root", _session("lux-cli", "/", _beads(), kind="cli")))

        assert _labels_under(_submenu(menus, "lux-cli")) == ["Beads", "Details"]

    def test_a_client_at_the_root_does_not_take_the_bar_down_with_it(self) -> None:
        """The whole menu is composed at once, so one bad label cost everyone."""
        menus = _menus(
            ("root", _session("lux-cli", "/", _beads(), kind="cli")),
            ("lux", _session("claude", "/w/lux", _beads())),
        )

        assert _labels_under(_clients_menu(menus)) == ["lux", "lux-cli"]

    def test_two_clients_on_one_repository_are_numbered(self) -> None:
        menus = _menus(
            ("first", _session("claude", "/w/lux", _beads())),
            ("second", _session("lux · lux · #4b97", "/w/lux", _beads())),
        )

        assert _labels_under(_clients_menu(menus)) == ["lux", "lux (2)"]

    def test_a_menu_read_that_omits_a_client_does_not_rename_the_rest(self) -> None:
        """A departure is stated by the registry, never inferred from a read.

        This read shows only the second client, but nobody told the roster the
        first had gone, so its name is still held and the second is still the
        second. A name moves when a session is removed — see
        :meth:`test_the_client_left_alone_by_a_departure_loses_its_number`.
        """
        roster = ClientRoster()
        first = ("first", _session("claude", "/w/lux", _beads()))
        second = ("second", _session("claude", "/w/lux", _beads()))
        assert _labels_under(_clients_menu(_menus(first, second, roster=roster))) == [
            "lux",
            "lux (2)",
        ]

        menus = _menus(second, roster=roster)

        assert _labels_under(_clients_menu(menus)) == ["lux (2)"]

    def test_the_client_left_alone_by_a_departure_loses_its_number(self) -> None:
        """A number is for telling two clients apart; alone, there is nobody to tell."""
        roster = ClientRoster()
        first = ("first", _session("claude", "/w/lux", _beads()))
        second = ("second", _session("claude", "/w/lux", _beads()))
        _menus(first, second, roster=roster)

        roster.release([ConnectionId("first")])
        menus = _menus(second, roster=roster)

        assert _labels_under(_clients_menu(menus)) == ["lux"]

    def test_a_client_keeps_its_name_across_a_leg_that_re_attaches(self) -> None:
        """The window between an attach and its re-registration must not rename.

        Taking the listen slot clears the callbacks the last occupant owned, so
        for that moment the client holds none. Its name is not the menu's to
        release — it belongs to the connection, which never went away.
        """
        roster = ClientRoster()
        first = ("first", _session("claude", "/w/lux", _beads()))
        second = ("second", _session("claude", "/w/lux", _beads()))
        _menus(first, second, roster=roster)
        assert roster.held()[ConnectionId("second")] == "lux (2)"

        # The first client re-attaches its leg: identity and connection intact,
        # callbacks cleared until it registers again.
        reattached = ("first", _session("claude", "/w/lux"))
        _menus(reattached, second, roster=roster)  # the menu read in that window
        menus = _menus(first, second, roster=roster)  # and after re-registering

        assert _labels_under(_clients_menu(menus)) == ["lux", "lux (2)"]
        assert roster.held()[ConnectionId("first")] == "lux"
        assert roster.held()[ConnectionId("second")] == "lux (2)"

    def test_the_name_the_departed_client_held_is_free_for_the_next(self) -> None:
        roster = ClientRoster()
        first = ("first", _session("claude", "/w/lux", _beads()))
        second = ("second", _session("claude", "/w/lux", _beads()))
        _menus(first, second, roster=roster)

        # The first goes — the registry says so as it removes the session — and a
        # newcomer arrives on the repository it named. The survivor has the base
        # by then, so the newcomer is the one that is numbered.
        roster.release([ConnectionId("first")])
        third = ("third", _session("claude", "/w/lux", _beads()))
        menus = _menus(second, third, roster=roster)

        assert _labels_under(_clients_menu(menus)) == ["lux", "lux (2)"]
        assert roster.held()[ConnectionId("second")] == "lux"
        assert roster.held()[ConnectionId("third")] == "lux (2)"


class TestTheDetailsCommand:
    """Every client's submenu carries the Hub's own command, in the same place."""

    def test_details_is_the_last_entry_under_a_rule(self) -> None:
        menus = _menus(("lux", _session("claude", "/w/lux", _beads())))

        items = _submenu(menus, "lux").items
        assert isinstance(items[-2], MenuSeparator)
        assert isinstance(items[-1], MenuAction)
        assert items[-1].label == "Details"

    def test_a_client_with_only_details_still_shows_the_same_shape(self) -> None:
        """Details never stands alone: the client registered something to be here."""
        menus = _menus(("lux", _session("claude", "/w/lux", _beads())))

        assert _labels_under(_submenu(menus, "lux"))[-1] == "Details"

    def test_the_details_id_names_the_hub_not_the_client(self) -> None:
        conn = ConnectionId("lux")
        menus = _menus(("lux", _session("claude", "/w/lux", _beads())))

        details = _submenu(menus, "lux").items[-1]
        assert isinstance(details, MenuAction)
        invocation = CallbackInvocation.from_menu_id(details.id)
        assert invocation.connection_id == conn
        assert invocation.is_details

    def test_a_clients_own_command_is_not_the_details_command(self) -> None:
        menus = _menus(("lux", _session("claude", "/w/lux", _beads())))

        beads = _submenu(menus, "lux").items[0]
        assert isinstance(beads, MenuAction)
        assert not CallbackInvocation.from_menu_id(beads.id).is_details


class TestWhatContributesNothing:
    """Only a live, named client that registered something reaches the menu."""

    def test_an_unidentified_client_contributes_no_submenu(self) -> None:
        # Reachable by push and holding an entry, but it never said who it is.
        bare = ClientSession(0.0).attached(_SilentLeg()).with_callback(_beads())

        assert _menus(("bare", bare)) == []

    def test_an_identified_client_with_no_callbacks_contributes_nothing(self) -> None:
        session = _session("claude", "/w/lux")  # identified, registered no command

        assert _menus(("lux", session)) == []

    def test_a_client_with_no_entry_is_still_named(self) -> None:
        """Naming is presence; membership is registration. They are not the same.

        A client that holds no command has no submenu, but it is on the roster,
        so the moment it registers one it appears under the name it already had.
        """
        roster = ClientRoster()

        menus = _menus(("lux", _session("claude", "/w/lux")), roster=roster)

        assert menus == []
        assert roster.held() == {ConnectionId("lux"): "lux"}

    def test_an_unidentified_client_takes_no_name(self) -> None:
        """Nothing anonymous is on the roster."""
        roster = ClientRoster()
        bare = ClientSession(0.0).attached(_SilentLeg()).with_callback(_beads())

        _menus(("bare", bare), roster=roster)

        assert roster.held() == {}


class TestTheReplica:
    """What the replicator sends is the composed menu, as wire."""

    def test_replica_nests_a_client_under_clients(self) -> None:
        from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
        from punt_lux.domain.hub.hub_clients import HubClientRegistry

        registry = HubClientRegistry()
        conn = ConnectionId("lux")
        leg = _SilentLeg()
        identity = ClientIdentity(
            kind="applet", name="lux · lux · #4b97", repo="/w/lux"
        )
        registry.attach_listener(conn, identity, leg)
        registry.register_callback(
            conn, SessionCallback(id="beads", label="Beads"), leg
        )

        wire = CallbackMenuReplica(registry).callback_menu_wire()

        assert wire == [
            {
                "label": "Clients",
                "items": [
                    {
                        "label": "lux",
                        "items": [
                            {
                                "label": "Beads",
                                "id": CallbackInvocation(conn, "beads").menu_id,
                            },
                            {"label": "---"},
                            {
                                "label": "Details",
                                "id": CallbackInvocation.details(conn).menu_id,
                            },
                        ],
                    }
                ],
            }
        ]

    def test_the_replica_and_the_hub_read_name_a_client_the_same(self) -> None:
        """One roster: what the display shows and what list_menus reports agree."""
        from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
        from punt_lux.domain.hub.hub_clients import HubClientRegistry

        registry = HubClientRegistry()
        beads = SessionCallback(id="beads", label="Beads")
        for name in ("first", "second"):
            conn, leg = ConnectionId(name), _SilentLeg()
            registry.attach_listener(
                conn, ClientIdentity(kind="mcp-session", name=name, repo="/w/lux"), leg
            )
            registry.register_callback(conn, beads, leg)

        wire = CallbackMenuReplica(registry).callback_menu_wire()
        read = CallbackMenu.from_named(registry.named_sessions())

        clients = wire[0]["items"]
        assert isinstance(clients, list)
        assert [client["label"] for client in clients] == ["lux", "lux (2)"]
        assert _labels_under(read[0]) == ["lux", "lux (2)"]

    def test_the_bar_stops_naming_a_lone_client_after_a_ghost_when_it_goes(
        self,
    ) -> None:
        """The live defect, end to end: what the display is sent after a restart.

        The outgoing session's applet still holds ``lux`` while owning no menu
        entry, so the only submenu on the bar is the newcomer's, labelled
        ``lux (2)`` — a number with nothing in sight to be a second of. The moment
        the ghost is let go the newcomer holds the base, and the next send says so.
        """
        from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
        from punt_lux.domain.hub.hub_clients import HubClientRegistry

        registry = HubClientRegistry()
        ghost, arriving = ConnectionId("outgoing"), ConnectionId("incoming")
        registry.record(
            ghost,
            ClientIdentity(kind="applet", name="lux · lux · #4b97", repo="/w/lux"),
        )
        leg = _SilentLeg()
        registry.attach_listener(
            arriving,
            ClientIdentity(kind="applet", name="lux · lux · #f00d", repo="/w/lux"),
            leg,
        )
        registry.register_callback(
            arriving, SessionCallback(id="beads", label="Beads"), leg
        )
        replica = CallbackMenuReplica(registry)
        assert _labels_under(
            _clients_menu(CallbackMenu.from_named(registry.named_sessions()))
        ) == ["lux (2)"]

        registry.discard(ghost)

        clients = replica.callback_menu_wire()[0]["items"]
        assert isinstance(clients, list)
        assert [client["label"] for client in clients] == ["lux"]

    def test_replica_is_empty_when_no_client_has_a_callback(self) -> None:
        from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
        from punt_lux.domain.hub.hub_clients import HubClientRegistry

        registry = HubClientRegistry()
        registry.record(
            ConnectionId("lux"), ClientIdentity(kind="mcp-session", name="lux")
        )

        assert CallbackMenuReplica(registry).callback_menu_wire() == []
