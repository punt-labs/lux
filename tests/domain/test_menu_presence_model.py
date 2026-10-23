"""The executable invariants of the menu-presence model, over seeded random walks.

``docs/menu_presence.tex`` proves three invariants for a bounded carrier. This
walks the same operations against the real lifecycle, a recording marker and the
production roster and label readers, and checks the same three after every step:

- **P1** with no menu mark pending, every live session that earns an entry is in
  the last pushed roster, and nothing in it is unregistered;
- **P2** a departing session that earned an entry fires exactly one sink, and no
  session ever fires more than one;
- **P3** a live session's scenes show its current label unless a mark for that
  scene is pending.

A failing seed is named in the message with the steps that led to it; pin it as
its own regression test.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Self, final

import pytest

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.frame_owner_facts import FrameOwnerFacts
from punt_lux.protocol.elements.text import TextElement

_CONNECTIONS = (ConnectionId("c0"), ConnectionId("c1"))
_STEPS = 60
_SEEDS = range(300)
_LEASE_SPAN = 2000.0  # one lapse step outlasts any kind's lease


@final
class _Dice:
    """A reproducible source of choices: the same seed walks the same steps."""

    _state: int
    __slots__ = ("_state",)

    def __new__(cls, seed: int) -> Self:
        self = super().__new__(cls)
        self._state = seed * 2654435761 % 2**32 or 1
        return self

    def choice[T](self, options: Sequence[T]) -> T:
        # xorshift32: enough spread for a walk, and no hidden global state.
        self._state ^= (self._state << 13) % 2**32
        self._state ^= self._state >> 17
        self._state ^= (self._state << 5) % 2**32
        return options[self._state % len(options)]


@final
class _Clock:
    now: float
    __slots__ = ("now",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.now = 0.0
        return self

    def __call__(self) -> float:
        return self.now


@final
class _Leg:
    def wake(self) -> None:
        """Occupies the slot only."""


@final
class _Presence:
    """The marker and the one shared sink: what the Hub tells the replicator."""

    menus_pending: bool
    scenes_pending: set[SceneId]
    fires: dict[ConnectionId, int]
    __slots__ = ("fires", "menus_pending", "scenes_pending")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.menus_pending = False
        self.scenes_pending = set()
        self.fires = {}
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.scenes_pending.add(scene_id)

    def mark_menus(self) -> None:
        self.menus_pending = True

    def __call__(self, connection_id: ConnectionId, /) -> None:
        self.fires[connection_id] = self.fires.get(connection_id, 0) + 1
        self.mark_menus()


@dataclass(slots=True)
class _World:
    """The Hub under test, and what the Display last drew from it."""

    clock: _Clock = field(default_factory=_Clock)
    presence: _Presence = field(default_factory=_Presence)
    factory: HubStoreFactory = field(init=False)
    facts: FrameOwnerFacts = field(init=False)
    legs: dict[ConnectionId, _Leg] = field(default_factory=dict)
    scenes: dict[ConnectionId, set[SceneId]] = field(default_factory=dict)
    shown: frozenset[ConnectionId] = frozenset()
    drawn_labels: dict[SceneId, str | None] = field(default_factory=dict)
    trace: list[str] = field(default_factory=list)
    serial: int = 0

    def __post_init__(self) -> None:
        self.factory = HubStoreFactory(self.clock, Hub())
        self.factory.lifecycle.present_as(self.presence, self.presence)
        listing = ClientListing(
            self.factory.display, self.factory.clients, Hub(), lambda _c: 0
        )
        self.facts = FrameOwnerFacts(self.factory.display, listing)

    def label_of(self, scene: SceneId) -> str | None:
        return self.facts.facts_for(scene).scope_label


def _identity(conn: ConnectionId, kind: str) -> ClientIdentity:
    name = f"claude-{conn}"
    if kind == "applet":
        return ClientIdentity(
            kind="applet", name=f"lux · lux · #{conn[-1]} · beads", repo="/w/lux"
        )
    return ClientIdentity(kind=kind, name=name, repo="/w/lux")  # type: ignore[arg-type]  # one of the kinds


@final
class _Walk:
    """One random walk's operations, each a small step against the world."""

    _world: _World
    _rng: _Dice
    __slots__ = ("_rng", "_world")

    def __new__(cls, world: _World, rng: _Dice) -> Self:
        self = super().__new__(cls)
        self._world = world
        self._rng = rng
        return self

    def step(self) -> None:
        conn = self._rng.choice(_CONNECTIONS)
        name = self._rng.choice(sorted(_OPERATIONS))
        self._world.trace.append(f"{name}({conn})")
        self._world.serial += 1
        _OPERATIONS[name](self._world, conn, self._rng)


def _identify(kind: str) -> Callable[[_World, ConnectionId, _Dice], None]:
    def step(world: _World, conn: ConnectionId, _rng: _Dice) -> None:
        world.factory.lifecycle.identify(conn, _identity(conn, kind))

    return step


def _attach(kind: str) -> Callable[[_World, ConnectionId, _Dice], None]:
    def step(world: _World, conn: ConnectionId, _rng: _Dice) -> None:
        world.legs[conn] = _Leg()
        world.factory.lifecycle.attach(conn, _identity(conn, kind), world.legs[conn])

    return step


def _register(world: _World, conn: ConnectionId, _rng: _Dice) -> None:
    callback = SessionCallback(id=f"cb{world.serial}", label="Run")
    world.factory.lifecycle.register_callback(conn, callback)


def _detach(world: _World, conn: ConnectionId, _rng: _Dice) -> None:
    if conn in world.legs:
        world.factory.lifecycle.detach(conn, world.legs[conn])


def _lapse(world: _World, _conn: ConnectionId, rng: _Dice) -> None:
    world.clock.now += rng.choice((10.0, 100.0, _LEASE_SPAN))


def _renew(world: _World, conn: ConnectionId, _rng: _Dice) -> None:
    world.factory.lifecycle.renew(conn)


def _arrive(world: _World, conn: ConnectionId, _rng: _Dice) -> None:
    world.factory.lifecycle.arrive(conn)


def _sweep(world: _World, _conn: ConnectionId, _rng: _Dice) -> None:
    _departing(world, lambda: world.factory.lifecycle.depart_lapsed(frozenset()))


def _drop(world: _World, conn: ConnectionId, _rng: _Dice) -> None:

    def leave() -> frozenset[ConnectionId]:
        world.factory.lifecycle.depart(conn)
        return frozenset({conn})

    _departing(world, leave)


def _menus(world: _World, _conn: ConnectionId, _rng: _Dice) -> None:
    _push_menus(world)


def _touched(world: _World, conn: ConnectionId, _rng: _Dice) -> None:
    _touch(world, conn)


def _scenes(world: _World, _conn: ConnectionId, _rng: _Dice) -> None:
    _push_scenes(world)


_OPERATIONS: dict[str, Callable[[_World, ConnectionId, _Dice], None]] = {
    "identify_agent": _identify("mcp-session"),
    "identify_cli": _identify("cli"),
    "attach_agent": _attach("mcp-session"),
    "attach_applet": _attach("applet"),
    "record": _arrive,
    "register_callback": _register,
    "detach": _detach,
    "lapse": _lapse,
    "renew": _renew,
    "sweep": _sweep,
    "drop": _drop,
    "push": _menus,
    "touch_scenes": _touched,
    "push_scenes": _scenes,
}


def _earning(world: _World) -> dict[ConnectionId, bool]:
    """Each registered session that earns an entry, and whether its lease is live."""
    now = world.clock()
    return {
        conn: session.is_live(now)
        for conn, session in world.factory.clients.sessions().items()
        if session.earns_menu_presence()
    }


def _departing(world: _World, leave: Callable[[], frozenset[ConnectionId]]) -> None:
    """Depart, checking P2: an earning departer fires exactly one sink."""
    earners = frozenset(_earning(world))
    registered = frozenset(world.factory.clients.sessions())
    before = dict(world.presence.fires)
    gone = leave()
    for conn in gone & registered:
        fired = world.presence.fires.get(conn, 0) - before.get(conn, 0)
        assert fired <= 1, f"{conn} fired {fired} sinks"
        if conn in earners:
            assert fired == 1, f"earning {conn} departed with {fired} sinks"
        world.scenes.pop(conn, None)
    for scene in [s for s in world.drawn_labels if _owner_gone(world, s)]:
        del world.drawn_labels[scene]
        world.presence.scenes_pending.discard(scene)


def _owner_gone(world: _World, scene: SceneId) -> bool:
    return not world.factory.display.scene_owners(scene)


def _push_menus(world: _World) -> None:
    if world.presence.menus_pending:
        world.shown = frozenset(conn for conn, live in _earning(world).items() if live)
        world.presence.menus_pending = False


def _touch(world: _World, conn: ConnectionId) -> None:
    if conn not in world.factory.clients.sessions():
        return
    scene = SceneId(f"{conn}-s{world.serial % 2}")
    world.factory.display.replace_scene(conn, scene, [TextElement(id="t", content="x")])
    world.scenes.setdefault(conn, set()).add(scene)
    world.drawn_labels[scene] = world.label_of(scene)


def _push_scenes(world: _World) -> None:
    for scene in sorted(world.presence.scenes_pending):
        if not _owner_gone(world, scene):
            world.drawn_labels[scene] = world.label_of(scene)
    world.presence.scenes_pending.clear()


def _check(world: _World) -> None:
    """P1 and P3 after a step."""
    registered = set(world.factory.clients.sessions())
    if not world.presence.menus_pending:
        live_earning = {c for c, live in _earning(world).items() if live}
        assert live_earning <= world.shown, f"P1: {live_earning - world.shown} missing"
        assert world.shown <= registered, f"P1: unregistered {world.shown - registered}"
    now = world.clock()
    for conn, session in world.factory.clients.sessions().items():
        if not session.is_live(now):
            continue
        for scene in world.scenes.get(conn, ()):
            if scene in world.presence.scenes_pending or _owner_gone(world, scene):
                continue
            assert world.drawn_labels[scene] == world.label_of(scene), (
                f"P3: {scene} draws {world.drawn_labels[scene]!r}, "
                f"is {world.label_of(scene)!r}"
            )


@pytest.mark.parametrize("seed", _SEEDS)
def test_every_invariant_holds_after_every_step(seed: int) -> None:
    world = _World()
    walk = _Walk(world, _Dice(seed))
    for _ in range(_STEPS):
        walk.step()
        try:
            _check(world)
        except AssertionError as failure:
            trace = " -> ".join(world.trace)
            pytest.fail(f"seed {seed}: {failure}\n  steps: {trace}")
