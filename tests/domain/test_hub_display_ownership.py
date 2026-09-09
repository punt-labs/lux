"""HubDisplay.apply enforces ownership on SetProperty and RemoveElement.

Without the check, any connection could mutate or evict any other
connection's elements from the Hub mirror. Display-side ``Display.apply``
already gates on ownership; the Hub mirror must enforce the same rule.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

import pytest

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.departure_cascade import DepartureCascade
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.owner import Owner
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId, Topic
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty

_SCENE = SceneId("ownership-scene")
_OWNER = ConnectionId("owner-conn")
_STRANGER = ConnectionId("stranger-conn")
_ELEMENT_ID = ElementId("element")


class _Clock:
    """A hand-advanced monotonic clock, so lease expiry is deterministic."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _cli(name: str) -> ClientIdentity:
    """A ``cli``-kind identity — the 90s lease the reaping tests advance past."""
    return ClientIdentity(kind="cli", name=name, repo="/w/lux")


def _mcp(name: str) -> ClientIdentity:
    """An ``mcp-session``-kind identity — the 1800s lease that outlives a cli's."""
    return ClientIdentity(kind="mcp-session", name=name, repo="/w/lux")


@dataclass(frozen=True, slots=True)
class _WireLeaf:
    """Wire-shaped leaf — satisfies the Element Protocol structurally."""

    id: str
    kind: Literal["leaf"] = "leaf"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]))


def _seed_owner_element() -> HubDisplay:
    """Install one element owned by ``_OWNER`` and return the populated display."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    hub_display.register_client(_STRANGER)
    hub_display.apply(
        _OWNER,
        AddElement(
            scene_id=_SCENE,
            element=_WireLeaf(id=str(_ELEMENT_ID)),
            parent_id=None,
        ),
    )
    return hub_display


def test_remove_element_rejects_non_owner() -> None:
    """A stranger cannot RemoveElement against an element they do not own."""
    hub_display = _seed_owner_element()

    with pytest.raises(HubOwnershipError):
        hub_display.apply(
            _STRANGER,
            RemoveElement(scene_id=_SCENE, element_id=_ELEMENT_ID),
        )
    # The owner's element survives the rejected removal.
    assert hub_display.owner_of(_SCENE, _ELEMENT_ID) == _OWNER


def test_set_property_rejects_non_owner() -> None:
    """A stranger cannot SetProperty against an element they do not own.

    The ownership check fires before the frozen-wire ``TypeError`` would,
    so the stranger sees ``HubOwnershipError``, not a misleading
    "frozen element" message.
    """
    hub_display = _seed_owner_element()

    with pytest.raises(HubOwnershipError):
        hub_display.apply(
            _STRANGER,
            SetProperty(
                scene_id=_SCENE,
                element_id=_ELEMENT_ID,
                field="label",
                value="hijacked",
            ),
        )


def test_owner_can_still_remove_their_own_element() -> None:
    """The check rejects strangers, not the legitimate owner."""
    hub_display = _seed_owner_element()

    hub_display.apply(
        _OWNER,
        RemoveElement(scene_id=_SCENE, element_id=_ELEMENT_ID),
    )


# -- replace_scene ---------------------------------------------------------


def test_replace_scene_installs_fresh_roots() -> None:
    """``replace_scene`` with no prior scene installs all roots."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)

    leaf_a = _WireLeaf(id="a")
    leaf_b = _WireLeaf(id="b")
    hub_display.replace_scene(_OWNER, _SCENE, [leaf_a, leaf_b])

    assert hub_display.owner_of(_SCENE, ElementId("a")) == _OWNER
    assert hub_display.owner_of(_SCENE, ElementId("b")) == _OWNER
    roots = hub_display.scene_roots(_SCENE)
    root_ids = {e.id for e in roots}
    assert root_ids == {"a", "b"}


def test_replace_scene_removes_old_roots_and_installs_new() -> None:
    """``replace_scene`` replaces the existing scene — old roots are gone."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)

    old = _WireLeaf(id="old")
    hub_display.replace_scene(_OWNER, _SCENE, [old])
    assert hub_display.owner_of(_SCENE, ElementId("old")) == _OWNER

    new = _WireLeaf(id="new")
    hub_display.replace_scene(_OWNER, _SCENE, [new])

    roots = hub_display.scene_roots(_SCENE)
    root_ids = {e.id for e in roots}
    assert root_ids == {"new"}

    from punt_lux.domain.hub.element_index import UnknownElementError

    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, ElementId("old"))


def test_reshow_from_a_new_connection_replaces_a_departed_sessions_roots() -> None:
    """A re-show clears an orphan a departed session left, keeping single ownership.

    The original session shows a scene, then disconnects — its roots stand, owned
    by its departed id. A new connection re-shows the same scene_id. Because the
    scene is the unit of replacement, the orphan is torn down and only the new
    roots remain, all owned by the new connection — no ghost content, no duplicate.
    """
    hub_display = HubDisplay()
    departed = ConnectionId("departed-session")
    fresh = ConnectionId("fresh-session")

    hub_display.register_client(departed)
    hub_display.replace_scene(departed, _SCENE, [_WireLeaf(id="old")])
    hub_display.drop_connection(departed)  # session gone, its root stands orphaned

    hub_display.replace_scene(fresh, _SCENE, [_WireLeaf(id="new")])

    roots = hub_display.scene_roots(_SCENE)
    assert {e.id for e in roots} == {"new"}  # orphan gone, only the new root
    assert hub_display.owner_of(_SCENE, ElementId("new")) == fresh
    # A single owning connection, carrying no declared identity (none was set).
    assert hub_display.scene_owners(_SCENE) == (Owner(fresh),)


def test_show_scene_snapshots_the_identity_onto_every_owner() -> None:
    """The connection's declared identity is recorded as each root's attribution."""
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.scene_presentation import ScenePresentation

    hub_display = HubDisplay()
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    hub_display.identify_client(_OWNER, identity)  # declared before showing
    hub_display.show_scene(
        _OWNER,
        _SCENE,
        [_WireLeaf(id="a"), _WireLeaf(id="b")],
        ScenePresentation(frame_id=str(_SCENE)),
    )

    owners = hub_display.scene_owners(_SCENE)
    assert owners == (Owner(_OWNER, identity),)  # one connection, its identity


def test_departing_a_connection_releases_ownership_but_keeps_the_content() -> None:
    """Depart releases ownership to unowned; it does not tear the content down.

    A departed connection's installed content stays standing — a later frame
    close, clear, or TTL removes it, or a live connection reclaims it through
    the ordinary unowned-claim path — but nobody is attributed to it the
    moment it departs, identity declared or not.
    """
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.scene_presentation import ScenePresentation

    hub_display = HubDisplay()
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    hub_display.identify_client(_OWNER, identity)
    hub_display.show_scene(
        _OWNER,
        _SCENE,
        [_WireLeaf(id="a")],
        ScenePresentation(frame_id=str(_SCENE)),
    )

    hub_display.drop_connection(_OWNER)  # the command exits and departs

    assert _OWNER not in hub_display.client_sessions()  # gone from the live registry
    assert [e.id for e in hub_display.scene_roots(_SCENE)] == ["a"]  # content stands
    assert hub_display.scene_owners(_SCENE) == ()  # but ownership is released


def test_clear_leaves_a_root_another_connection_owns_in_a_shared_scene() -> None:
    """``clear`` removes only the caller's roots, never a co-owner's in the scene.

    Unlike a re-show (whole-scene replacement), a clear is owner-scoped: one
    connection clearing its UI must not evict a root another connection still holds
    in the same scene.
    """
    from punt_lux.domain.hub.scene_writer import HubSceneWriter

    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    hub_display.register_client(_STRANGER)
    hub_display.apply(
        _OWNER,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="mine"), parent_id=None),
    )
    hub_display.apply(
        _STRANGER,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="theirs"), parent_id=None),
    )

    HubSceneWriter(hub_display).clear(_OWNER)

    assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"theirs"}


# -- reap-and-release: a departed connection's ownership is released -------


def test_reap_of_a_dead_connection_releases_its_scenes() -> None:
    """KT1: a lapsed connection is dropped and every scene it owned unowned.

    Nobody has renewed ``dead``'s lease; once it has lapsed, a write from any
    other live connection triggers the sweep-and-release, and ``dead``'s
    scene is left with no owner at all.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    dead = ConnectionId("dead-conn")
    live = ConnectionId("live-conn")
    hub_display.identify_client(dead, _cli("dead"))
    hub_display.apply(
        dead,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )
    assert hub_display.scene_owners(_SCENE) == (Owner(dead, _cli("dead")),)

    clock.advance(91.0)  # past the 90s cli lease; dead never renews again
    hub_display.register_client(live)
    other_scene = SceneId("unrelated-scene")
    hub_display.apply(
        live,
        AddElement(scene_id=other_scene, element=_WireLeaf(id="x"), parent_id=None),
    )  # any ownership-gated write triggers the pull-based sweep

    assert hub_display.elements_owned_by(dead) == ()
    assert hub_display.scene_owners(_SCENE) == ()


def test_a_reconnect_before_reap_is_blocked_from_the_predecessors_scene() -> None:
    """RB1: a predecessor still inside its lease keeps blocking a claim.

    Reap-and-release must never release a connection whose lease has not
    lapsed — a live successor sharing its identity is blocked exactly as any
    other stranger would be, until the predecessor is actually reaped.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    predecessor = ConnectionId("voxd-old")
    successor = ConnectionId("voxd-new")
    hub_display.identify_client(predecessor, _cli("voxd"))
    hub_display.apply(
        predecessor,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )
    hub_display.identify_client(successor, _cli("voxd"))

    with pytest.raises(HubOwnershipError):
        hub_display.apply(
            successor,
            SetProperty(
                scene_id=_SCENE,
                element_id=ElementId("track"),
                field="label",
                value="now playing",
            ),
        )


def test_a_reconnect_after_reap_claims_the_released_scene() -> None:
    """RA1: reconnect-after-departure claims the scene the predecessor left.

    Without the reap-and-release wiring this raises ``HubOwnershipError``
    forever: nothing ever releases ``predecessor``'s ownership once its lease
    lapses, so ``successor`` — a live connection sharing its identity — stays
    shadowed by a corpse for good. Verified fail-first by stubbing the sweep
    step ``apply`` runs to a no-op: the removal below then raises
    ``HubOwnershipError``; with the fix wired, the sweep runs before the
    ownership check and the removal succeeds.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    predecessor = ConnectionId("voxd-old")
    successor = ConnectionId("voxd-new")
    hub_display.identify_client(predecessor, _cli("voxd"))
    hub_display.apply(
        predecessor,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )

    clock.advance(91.0)  # past the 90s cli lease; predecessor never renews again
    hub_display.identify_client(successor, _cli("voxd"))

    # No HubOwnershipError: the reap-and-release ran before this check, so the
    # scene predecessor left behind is unowned by the time successor acts on it.
    hub_display.apply(
        successor,
        RemoveElement(scene_id=_SCENE, element_id=ElementId("track")),
    )

    assert {e.id for e in hub_display.scene_roots(_SCENE)} == set()
    assert hub_display.elements_owned_by(predecessor) == ()


def test_reaping_one_identitys_connection_never_blocks_an_unrelated_identity() -> None:
    """MI1: reaping one identity's dead connection leaves another's scene alone.

    I3's identity comparison must genuinely distinguish connections rather
    than benefit from there being only one identity in play — ``live``'s own
    write triggers the sweep that reaps ``dead``, and ``live``'s scene is
    untouched by it.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    dead = ConnectionId("voxd-old")
    live = ConnectionId("claude-mcp")
    other_scene = SceneId("claude-scene")
    hub_display.identify_client(dead, _cli("voxd"))
    hub_display.identify_client(live, _mcp("claude"))
    hub_display.apply(
        dead,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )
    hub_display.apply(
        live,
        AddElement(scene_id=other_scene, element=_WireLeaf(id="panel"), parent_id=None),
    )

    clock.advance(91.0)  # past the cli lease; the mcp-session lease (1800s) survives
    # live's own write is the trigger: it must reap dead without disturbing
    # anything live already owns, including the untouched "panel" root.
    hub_display.apply(
        live,
        AddElement(
            scene_id=other_scene, element=_WireLeaf(id="panel2"), parent_id=None
        ),
    )

    assert hub_display.owner_of(other_scene, ElementId("panel")) == live
    assert hub_display.owner_of(other_scene, ElementId("panel2")) == live
    assert hub_display.elements_owned_by(dead) == ()


def test_continuous_renewal_keeps_ownership_through_repeated_reap_triggers() -> None:
    """LR1: a connection that keeps renewing is never reaped, so it keeps its scene.

    Every ``apply`` call is itself an opportunity to reap a lapsed lease.
    ``steady`` renews before its 90s cli lease would lapse on every one of
    five such opportunities, so it must never be swept and must keep its
    scene throughout — the property the pure-registry
    ``test_hub_clients.py::test_any_contact_renews_the_lease`` already proves
    for the lease, extended here to prove ownership survives it too.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    steady = ConnectionId("steady-conn")
    hub_display.identify_client(steady, _cli("steady"))
    hub_display.apply(
        steady,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="a"), parent_id=None),
    )

    for i in range(5):
        clock.advance(60.0)  # inside the 90s cli lease if renewed each time
        hub_display.register_client(steady)  # a bare contact renews the lease
        # Each apply is itself a reap opportunity; the write's own content
        # (a fresh element) is incidental — the point is that "a" survives it.
        hub_display.apply(
            steady,
            AddElement(
                scene_id=_SCENE, element=_WireLeaf(id=f"extra-{i}"), parent_id=None
            ),
        )

    assert hub_display.owner_of(_SCENE, ElementId("a")) == steady


def test_a_read_alone_never_releases_or_strands_a_lapsed_connection() -> None:
    """RD1/RD2: a read filters what it shows; the atomic write path is what departs.

    Reading through a lapsed connection any number of times, with no
    intervening write from any connection, must change nothing — the
    connection stays registered on paper and keeps every scene it owned.
    Only the live connection's own write (the atomic sweep-and-release path)
    actually departs it.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    dead = ConnectionId("dead-conn")
    live = ConnectionId("live-conn")
    hub_display.identify_client(dead, _cli("dead"))
    hub_display.apply(
        dead,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )
    clock.advance(91.0)  # past the 90s cli lease; dead never renews again

    # RD2: reading repeatedly strands nothing — same answer every time.
    for _ in range(3):
        assert dead not in hub_display.client_sessions()  # filtered from the live view
        assert dead in hub_display.clients.sessions()  # still registered on paper
        assert hub_display.elements_owned_by(dead) == ((_SCENE, ElementId("track")),)
        assert hub_display.scene_owners(_SCENE) == (Owner(dead, _cli("dead")),)

    # The atomic path: a live connection's own write, and nothing else, departs it.
    hub_display.register_client(live)
    hub_display.apply(
        live,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="other"), parent_id=None),
    )

    assert not hub_display.is_client(dead)
    assert hub_display.elements_owned_by(dead) == ()  # only now released


def test_a_lapsed_writer_survives_its_own_next_apply() -> None:
    """SR1: a long-lived writer's own write renews it before anything can sweep.

    ``writer``'s only contact is ``apply`` itself, with no explicit
    ``identify``/``register_client`` in between — the exact shape of a
    connection that shows once, then only ever patches. The self-exclusion
    in ``apply``'s sweep means this single call can never catch its own
    caller; the renewal that same call performs is what protects it from a
    *later*, separate sweep (the background timer, or another connection's
    own write) that would otherwise still find it lapsed.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    writer = ConnectionId("long-lived-writer")
    hub_display.identify_client(writer, _cli("writer"))
    hub_display.apply(
        writer,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )

    clock.advance(91.0)  # past the 90s cli lease; nothing else ever renews it

    # The self-reap regression: this write must renew writer and succeed
    # against its own scene, not raise HubOwnershipError against a corpse
    # its own sweep just made of itself.
    hub_display.apply(
        writer,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track2"), parent_id=None),
    )
    assert hub_display.is_client(writer)
    assert hub_display.owner_of(_SCENE, ElementId("track")) == writer
    assert hub_display.owner_of(_SCENE, ElementId("track2")) == writer

    # Renewal, not just self-exclusion: a later, independent sweep (the
    # background timer) must not catch writer either, since its own write
    # just renewed it.
    reaped = hub_display.reap_lapsed_leases()
    assert writer not in reaped
    assert hub_display.is_client(writer)
    assert hub_display.owner_of(_SCENE, ElementId("track")) == writer


def test_a_lapsed_connection_is_reaped_by_the_timer_alone_on_an_idle_hub() -> None:
    """TR1: the round-2 regression — the bead's own reported scenario.

    Kill the connection's transport (simulated: nothing ever renews it
    again), wait one lease interval, and do nothing else — no read, no
    other connection's write, no explicit disconnect. The only thing that
    runs is the timer's own sweep, and it alone must reap and release.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    dead = ConnectionId("dead-conn")
    hub_display.identify_client(dead, _cli("dead"))
    hub_display.apply(
        dead,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )

    clock.advance(91.0)  # past the 90s cli lease; transport is gone, nobody renews

    reaped = hub_display.reap_lapsed_leases()  # the timer's own sweep, nothing else

    assert reaped == frozenset({dead})
    assert not hub_display.is_client(dead)
    assert hub_display.elements_owned_by(dead) == ()


def test_reap_lapsed_leases_touches_no_scene_when_nothing_has_lapsed() -> None:
    """TR3: the timer's sweep is a no-op on a Hub with no lapsed connection."""
    clock = _Clock()
    hub_display = HubDisplay(clock)
    live = ConnectionId("live-conn")
    hub_display.identify_client(live, _cli("live"))
    hub_display.apply(
        live,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )

    assert hub_display.reap_lapsed_leases() == frozenset()
    assert hub_display.is_client(live)
    assert hub_display.owner_of(_SCENE, ElementId("track")) == live


# -- cascade completeness: the full departure tail, not just registry+ownership --


def test_a_timer_reaped_connection_loses_its_full_cascade_not_just_registry_and_ownership() -> (  # noqa: E501
    None
):
    """CC1: a purely timer-reaped connection loses subs, writer, and inbox too.

    ``TimedReap`` (:meth:`HubDisplay.reap_lapsed_leases`) must reach every
    cascade leg, not just the registry-and-ownership pair the original
    reap-and-release fix covered.
    """
    clock = _Clock()
    isolated_hub = Hub()
    hub_display = HubDisplay(clock, hub=isolated_hub)
    conn = ConnectionId("cascade-timer")
    hub_display.identify_client(conn, _cli("cascade"))
    hub_display.apply(
        conn,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )
    isolated_hub.register_writer(conn, lambda _msg: None)
    isolated_hub.subscribe(conn, Topic("t"))
    fired: list[ConnectionId] = []

    def _sink(connection_id: ConnectionId) -> None:
        fired.append(connection_id)

    hub_display.bind_departure_sink(conn, _sink)

    clock.advance(91.0)  # past the 90s cli lease; nothing else ever renews it
    reaped = hub_display.reap_lapsed_leases()

    assert reaped == frozenset({conn})
    assert not isolated_hub.has_writer(conn)
    assert isolated_hub.topics_for(conn) == frozenset()
    assert fired == [conn]


def test_apply_clears_a_swept_connections_full_cascade_as_a_side_effect() -> None:
    """CC2: Claim's embedded sweep-of-others clears the swept full cascade too."""
    clock = _Clock()
    isolated_hub = Hub()
    hub_display = HubDisplay(clock, hub=isolated_hub)
    dead = ConnectionId("swept-dead")
    live = ConnectionId("swept-live")
    hub_display.identify_client(dead, _cli("dead"))
    hub_display.apply(
        dead,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )
    isolated_hub.register_writer(dead, lambda _msg: None)
    isolated_hub.subscribe(dead, Topic("t"))
    fired: list[ConnectionId] = []

    def _sink(connection_id: ConnectionId) -> None:
        fired.append(connection_id)

    hub_display.bind_departure_sink(dead, _sink)

    clock.advance(91.0)  # past the cli lease; live's own write triggers the sweep
    other_scene = SceneId("swept-other-scene")
    hub_display.identify_client(live, _mcp("live"))
    hub_display.apply(
        live,
        AddElement(scene_id=other_scene, element=_WireLeaf(id="x"), parent_id=None),
    )

    assert not isolated_hub.has_writer(dead)
    assert isolated_hub.topics_for(dead) == frozenset()
    assert fired == [dead]


def test_reaping_a_connection_with_no_side_state_touches_nothing_new() -> None:
    """CC3: a connection with no subscription, writer, or sink is a cascade no-op."""
    clock = _Clock()
    isolated_hub = Hub()
    hub_display = HubDisplay(clock, hub=isolated_hub)
    conn = ConnectionId("no-side-state")
    hub_display.identify_client(conn, _cli("bare"))

    clock.advance(91.0)
    reaped = hub_display.reap_lapsed_leases()  # must not raise

    assert reaped == frozenset({conn})
    assert not isolated_hub.has_writer(conn)


# -- reconnect-vs-reap mutual exclusion: the StoreLock fix -----------------


def test_a_reconnect_never_lands_inside_an_open_departure_cascade() -> None:
    """RR1: register_client under StoreLock closes the register_client-vs-reap race.

    Without the fix, ``register_client`` takes no lock, so a same-identity
    reconnect can land between a stale reap's registry removal and its
    cascade tail: the reconnect's fresh writer is installed, then the
    reap's delayed ``Hub.on_disconnect`` call wipes it out. With the fix,
    the reconnect blocks on the same ``StoreLock`` the reap holds across
    its whole critical section, so it can only proceed once the cascade has
    fully completed -- landing its fresh writer with nothing left to
    destroy it.

    The interleaving is forced deterministically: the cascade tail
    (``DepartureCascade.run_all``) is wrapped to signal it has been
    reached, then sleep briefly -- an explicit window for the reconnecting
    thread to attempt ``register_client`` concurrently, whether or not that
    call blocks.
    """
    clock = _Clock()
    isolated_hub = Hub()
    hub_display = HubDisplay(clock, hub=isolated_hub)
    conn = ConnectionId("reconnect-race")
    hub_display.identify_client(conn, _cli("race"))
    clock.advance(91.0)  # lapse conn's lease so reap_lapsed_leases will remove it

    tail_reached = threading.Event()
    original_run_all = DepartureCascade.run_all

    def _paused_run_all(
        self: DepartureCascade, connection_ids: frozenset[ConnectionId]
    ) -> None:
        tail_reached.set()
        threading.Event().wait(timeout=0.2)  # window for the racing reconnect
        original_run_all(self, connection_ids)

    new_writer_installed = threading.Event()

    def _reconnect() -> None:
        tail_reached.wait(timeout=2.0)
        hub_display.register_client(conn)  # blocks on StoreLock when fixed
        isolated_hub.register_writer(conn, lambda _msg: None)
        new_writer_installed.set()

    reconnect_thread = threading.Thread(target=_reconnect)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(DepartureCascade, "run_all", _paused_run_all)
        reconnect_thread.start()
        hub_display.reap_lapsed_leases()
        reconnect_thread.join(timeout=2.0)

    assert new_writer_installed.is_set()
    assert isolated_hub.has_writer(conn)
