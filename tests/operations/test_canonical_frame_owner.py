"""CanonicalFrameOwner — owner facts lifted from a scene to its whole frame.

Wraps FrameOwnerFacts: every scene composed into one frame must resolve to the
same owner, whichever scene the replicator sent last.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.display.replica import SceneReplica
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.canonical_frame_owner import CanonicalFrameOwner
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.frame_owner_facts import FrameOwnerFacts
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.protocol import Element, SceneMessage
from punt_lux.protocol.elements.text import TextElement
from tests.domain.test_hub_replicator import _FakeSender, _replicator

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.replicator import HubReplicator
    from punt_lux.domain.hub.scene_snapshot import SceneReader, SceneSnapshot


def _zero_inbox_depth(_connection_id: ConnectionId) -> int:
    """Report every connection's inbox empty; these tests don't exercise it."""
    return 0


def _reader(
    store: HubDisplay, clients: HubClientRegistry, hub: Hub
) -> CanonicalFrameOwner:
    listing = ClientListing(store, clients, hub, _zero_inbox_depth)
    return CanonicalFrameOwner(store, FrameOwnerFacts(store, listing))


def _identified_scene(
    store: HubDisplay,
    lifecycle: ClientLifecycle,
    clients: HubClientRegistry,
    connection: str,
    name: str,
) -> SceneId:
    """Register a named client and install one root it owns, returning its scene id."""
    conn = ConnectionId(connection)
    lifecycle.identify(conn, ClientIdentity(kind="cli", name=name))
    clients.named_sessions()  # the read that names it, as the menu build does
    scene_id = SceneId(f"{connection}-scene")
    store.replace_scene(conn, scene_id, [TextElement(id="t1", content="hi")])
    return scene_id


class TestAFrameComposingScenesWithDifferentOwners:
    def test_resolves_the_earliest_appearing_owner(self) -> None:
        # Two scenes, each owned by a different connection, share one frame;
        # the frame's owner is the one of the scene that appeared first.
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        first = _identified_scene(store, lifecycle, clients, "c1", name="alpha")
        second = _identified_scene(store, lifecycle, clients, "c2", name="beta")
        frame = ScenePresentation(frame_id="shared-frame")
        store.frames.record(first, frame)
        store.frames.record(second, frame)

        rows = _reader(store, clients, hub).facts_for_frame("shared-frame")

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"

    def test_seniority_is_first_appearance_not_lexical_scene_id(self) -> None:
        # The frame first receives "z-scene" (owner "z"), then "a-scene"
        # (owner "a"). Seniority is first-appearance order, so the canonical
        # owner is "z" -- lexical scene-id order would wrongly pick "a".
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        senior = _identified_scene(store, lifecycle, clients, "z", name="alpha")
        junior = _identified_scene(store, lifecycle, clients, "a", name="beta")
        frame = ScenePresentation(frame_id="shared-frame")
        store.frames.record(senior, frame)
        store.frames.record(junior, frame)

        rows = _reader(store, clients, hub).facts_for_frame("shared-frame")

        assert rows is not None
        assert dict(rows)["Connection"] == "z"

    def test_a_scene_shown_elsewhere_no_longer_names_the_frames_owner(self) -> None:
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        first = _identified_scene(store, lifecycle, clients, "c1", name="alpha")
        second = _identified_scene(store, lifecycle, clients, "c2", name="beta")
        store.frames.record(first, ScenePresentation(frame_id="elsewhere"))
        store.frames.record(second, ScenePresentation(frame_id="shared-frame"))

        rows = _reader(store, clients, hub).facts_for_frame("shared-frame")

        assert rows is not None
        assert dict(rows)["Connection"] == "c2"


class TestASelfFramedScene:
    def test_reports_its_own_owner(self) -> None:
        # A scene with no recorded presentation is framed by its own id.
        factory = HubStoreFactory()
        store = factory.display
        lifecycle = factory.lifecycle
        clients = factory.clients
        hub = Hub()
        scene_id = _identified_scene(store, lifecycle, clients, "c1", name="alpha")

        rows = _reader(store, clients, hub).facts_for_frame(str(scene_id))

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"

    def test_a_frame_nobody_shows_reports_none(self) -> None:
        factory = HubStoreFactory()
        store = factory.display
        clients = factory.clients
        hub = Hub()

        assert (
            _reader(store, clients, hub).facts_for_frame("nobody-framed-this") is None
        )


@final
class _ReshowingReader:
    """A scene reader that runs ``after_snapshot`` between capture and the send.

    Models a re-show or move that lands in the window after the worker copied a
    scene out of the store and before it resolves that scene's owner facts.
    """

    _inner: SceneReader
    _after_snapshot: Callable[[], None]
    __slots__ = ("_after_snapshot", "_inner")

    def __new__(cls, inner: SceneReader, after_snapshot: Callable[[], None]) -> Self:
        self = super().__new__(cls)
        self._inner = inner
        self._after_snapshot = after_snapshot
        return self

    def snapshot(self, scene_id: SceneId) -> SceneSnapshot:
        captured = self._inner.snapshot(scene_id)
        self._after_snapshot()
        return captured

    def live_scene_ids(self) -> tuple[SceneId, ...]:
        return self._inner.live_scene_ids()

    def reclaim_if_rootless(self, scene_id: SceneId) -> None:
        self._inner.reclaim_if_rootless(scene_id)


class TestAReplicatorSendRacingAReshow:
    def test_the_pushed_facts_belong_to_the_pushed_frame(self) -> None:
        # Frame "old" holds a1 (owner c1) and a2 (owner c2); frame "new" holds
        # b1 (owner c3). a1 is copied out for the "old" frame, then re-shown
        # into "new" before its facts resolve. The push still lands in "old",
        # so the facts it carries must be "old"'s owner now -- c2 -- and not
        # "new"'s canonical owner, which is a1's own owner, c1.
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        a1 = _identified_scene(store, lifecycle, clients, "c1", name="alpha")
        a2 = _identified_scene(store, lifecycle, clients, "c2", name="beta")
        b1 = _identified_scene(store, lifecycle, clients, "c3", name="gamma")
        store.frames.record(a1, ScenePresentation(frame_id="old"))
        store.frames.record(a2, ScenePresentation(frame_id="old"))
        store.frames.record(b1, ScenePresentation(frame_id="new"))

        def reshow() -> None:
            store.frames.record(a1, ScenePresentation(frame_id="new"))

        repl, sender, _provider, _lifecycle = _replicator(
            store,
            clients,
            owner_facts=_reader(store, clients, hub),
            reader=cast("SceneReader", _ReshowingReader(store.reader, reshow)),
        )
        repl.start()
        try:
            repl.mark_dirty(a1)
            assert sender.wait_sent(3.0)
        finally:
            repl.stop()

        (rows,) = sender.owner_facts
        assert (sender.frames[0], dict(rows or ())["Connection"]) == ("old", "c2")


class TestTheFramesCanonicalOwnerFollowsFrameEntryOrder:
    def test_a_scene_moved_into_the_frame_is_junior_to_one_already_there(self) -> None:
        # s1 is registered first overall, but s2 entered "shared" first and s1
        # was only re-shown into it afterwards: the frame's entry order is
        # s2, s1, so s2's owner is canonical -- not global registration order's s1.
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        s1 = _identified_scene(store, lifecycle, clients, "c1", name="alpha")
        s2 = _identified_scene(store, lifecycle, clients, "c2", name="beta")
        store.frames.record(s1, ScenePresentation(frame_id="a"))
        store.frames.record(s2, ScenePresentation(frame_id="shared"))
        store.frames.record(s1, ScenePresentation(frame_id="shared"))

        rows = _reader(store, clients, hub).facts_for_frame("shared")

        assert rows is not None
        assert dict(rows)["Connection"] == "c2"

    def test_a_re_show_in_place_keeps_the_canonical_owner(self) -> None:
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        s1 = _identified_scene(store, lifecycle, clients, "c1", name="alpha")
        s2 = _identified_scene(store, lifecycle, clients, "c2", name="beta")
        store.frames.record(s1, ScenePresentation(frame_id="shared"))
        store.frames.record(s2, ScenePresentation(frame_id="shared"))
        store.frames.record(s1, ScenePresentation(frame_id="shared", title="again"))

        rows = _reader(store, clients, hub).facts_for_frame("shared")

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"

    def test_when_the_canonical_scene_leaves_the_next_oldest_takes_over(self) -> None:
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        s1 = _identified_scene(store, lifecycle, clients, "c1", name="alpha")
        s2 = _identified_scene(store, lifecycle, clients, "c2", name="beta")
        s3 = _identified_scene(store, lifecycle, clients, "c3", name="gamma")
        for scene in (s1, s2, s3):
            store.frames.record(scene, ScenePresentation(frame_id="shared"))
        store.frames.record(s1, ScenePresentation(frame_id="elsewhere"))

        rows = _reader(store, clients, hub).facts_for_frame("shared")

        assert rows is not None
        assert dict(rows)["Connection"] == "c2"


def _ignore_stale(stale_ids: list[str]) -> None:
    """Take no interest in the element ids a replacement drops."""


@final
class _Pipeline:
    """A real replicator feeding a real Display replica, driven one send at a time."""

    _store: HubDisplay
    _replica: SceneReplica
    _repl: HubReplicator
    _sender: _FakeSender
    _cursor: int
    __slots__ = ("_cursor", "_repl", "_replica", "_sender", "_store")

    def __new__(cls, store: HubDisplay, clients: HubClientRegistry, hub: Hub) -> Self:
        self = super().__new__(cls)
        self._store = store
        self._replica = SceneReplica(on_scene_replaced=_ignore_stale)
        self._repl, self._sender, _provider, _lifecycle = _replicator(
            store, clients, owner_facts=_reader(store, clients, hub)
        )
        self._cursor = 0
        return self

    def __enter__(self) -> Self:
        self._repl.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._repl.stop()

    @property
    def marker(self) -> HubReplicator:
        """The replicator, as the dirty marker the installer reports to."""
        return self._repl

    def resend(self, scene: SceneId) -> str | None:
        """Resend ``scene``; return the owner connection the Display then shows."""
        self._repl.mark_dirty(scene)
        return self.collect(1)

    def collect(self, sends: int, frame: str = "shared") -> str | None:
        """Replay the next ``sends`` pushes; return ``frame``'s owner connection."""
        target = self._cursor + sends
        deadline = time.monotonic() + 3.0
        while len(self._sender.shows) < target:
            assert time.monotonic() < deadline, "the replicator never sent"
            time.sleep(0.005)
        for index in range(self._cursor, target):
            self._replica.handle_framed_scene(
                SceneMessage(
                    id=self._sender.shows[index],
                    elements=cast("list[Element]", self._sender.roots[index]),
                    frame_id=self._sender.frames[index] or "",
                    frame_owner_facts=self._sender.owner_facts[index],
                ),
                owner_fd=1,
            )
        self._cursor = target
        rows = self._replica.owner_facts_for(frame)
        return None if rows is None else dict(rows)["Connection"]


class TestTheDisplayAdoptsTheNextCanonicalOwnerWhenTheCanonicalSceneLeaves:
    """Hub replicator -> Display replica, end to end, in process."""

    @staticmethod
    def _two_scene_frame() -> tuple[HubStoreFactory, Hub, SceneId, SceneId]:
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        store = factory.display
        hub = Hub()
        s1 = _identified_scene(store, lifecycle, clients, "c1", name="alpha")
        s2 = _identified_scene(store, lifecycle, clients, "c2", name="beta")
        store.frames.record(s1, ScenePresentation(frame_id="shared"))
        store.frames.record(s2, ScenePresentation(frame_id="shared"))
        return factory, hub, s1, s2

    def test_a_blanked_canonical_scene_hands_the_frame_to_the_next_oldest(self) -> None:
        factory, hub, s1, s2 = self._two_scene_frame()
        clients = factory.clients
        store = factory.display
        with _Pipeline(store, clients, hub) as pipe:
            before = [pipe.resend(s1), pipe.resend(s2)]
            store.replace_scene(ConnectionId("c1"), s1, [])
            after = pipe.resend(s1)

        assert (before, after) == (["c1", "c1"], "c2")

    def test_a_moved_canonical_scene_leaves_the_frame_unknown_until_it_is_resent(
        self,
    ) -> None:
        factory, hub, s1, s2 = self._two_scene_frame()
        clients = factory.clients
        store = factory.display
        with _Pipeline(store, clients, hub) as pipe:
            pipe.resend(s1)
            pipe.resend(s2)
            store.frames.record(s1, ScenePresentation(frame_id="elsewhere"))
            after_move = pipe.resend(s1)
            after_resend = pipe.resend(s2)

        assert (after_move, after_resend) == (None, "c2")

    def test_a_moved_younger_scene_never_disturbs_the_frames_owner(self) -> None:
        factory, hub, s1, s2 = self._two_scene_frame()
        clients = factory.clients
        store = factory.display
        with _Pipeline(store, clients, hub) as pipe:
            pipe.resend(s1)
            pipe.resend(s2)
            store.frames.record(s2, ScenePresentation(frame_id="elsewhere"))
            after_move = pipe.resend(s2)

        assert after_move == "c1"


class TestAMoveOutOfAFrameNeedsNoManualResend:
    """Installing a scene into another frame resends the frame it left."""

    @staticmethod
    def _shared() -> tuple[HubStoreFactory, Hub, str]:
        factory = HubStoreFactory()
        lifecycle = factory.lifecycle
        clients = factory.clients
        hub = Hub()
        for connection, name in (("c1", "alpha"), ("c2", "beta")):
            lifecycle.identify(
                ConnectionId(connection), ClientIdentity(kind="cli", name=name)
            )
        clients.named_sessions()
        return factory, hub, ConnectionScopedId.compose(ConnectionId("c1"), "shared")

    @staticmethod
    def _show(installer: SceneInstaller, scene: str, frame: str) -> None:
        installer.install(
            SceneSubmission.of(
                [TextElement(id="t", content="x")],
                scene,
                ScenePresentation(frame_id=frame),
                None,
            ),
            owner=ConnectionId("c1"),
        )

    def _populated(
        self, pipe: _Pipeline, store: HubDisplay, frame: str
    ) -> SceneInstaller:
        installer = SceneInstaller(store, pipe.marker)
        self._show(installer, "s1", "shared")
        self._show(installer, "s2", "shared")
        pipe.collect(2, frame)
        # s2's root now belongs to c2; the frame's first scene stays c1's.
        s2 = SceneId(ConnectionScopedId.compose(ConnectionId("c1"), "s2"))
        store.replace_scene(ConnectionId("c2"), s2, [TextElement(id="t", content="x")])
        return installer

    def test_the_canonical_scene_moving_out_hands_the_frame_to_the_next(self) -> None:
        factory, hub, frame = self._shared()
        clients = factory.clients
        store = factory.display
        with _Pipeline(store, clients, hub) as pipe:
            installer = self._populated(pipe, store, frame)
            self._show(installer, "s1", "elsewhere")

            assert pipe.collect(2, frame) == "c2"

    def test_a_junior_scene_moving_out_leaves_the_frames_owner(self) -> None:
        factory, hub, frame = self._shared()
        clients = factory.clients
        store = factory.display
        with _Pipeline(store, clients, hub) as pipe:
            installer = self._populated(pipe, store, frame)
            self._show(installer, "s2", "elsewhere")

            assert pipe.collect(2, frame) == "c1"
