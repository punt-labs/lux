"""CanonicalFrameOwner — owner facts lifted from a scene to its whole frame.

Wraps FrameOwnerFacts: every scene composed into one frame must resolve to the
same owner, whichever scene the replicator sent last.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.display.replica import SceneReplica
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.canonical_frame_owner import CanonicalFrameOwner
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.frame_owner_facts import FrameOwnerFacts
from punt_lux.operations.queries import QueryOperations
from punt_lux.protocol import Element, SceneMessage
from punt_lux.protocol.elements.text import TextElement
from tests.domain.test_hub_replicator import _FakeSender, _replicator

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.replicator import HubReplicator
    from punt_lux.domain.hub.scene_snapshot import SceneReader, SceneSnapshot


class _ForbiddenPort:
    """A DisplayPort that fails the test if the read reaches around to it."""

    def query(self, method: str, params: object) -> object:
        msg = f"reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> object:
        msg = f"reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


def _zero_inbox_depth(_connection_id: ConnectionId) -> int:
    """Report every connection's inbox empty; these tests don't exercise it."""
    return 0


def _reader(store: HubDisplay, hub: Hub) -> CanonicalFrameOwner:
    clients = ClientListing(store, hub, _zero_inbox_depth)
    queries = QueryOperations(
        store,
        cast("object", _ForbiddenPort()),  # type: ignore[arg-type]  # structural port
        clients,
    )
    return CanonicalFrameOwner(store, FrameOwnerFacts(store, queries))


def _identified_scene(store: HubDisplay, connection: str, name: str) -> SceneId:
    """Register a named client and install one root it owns, returning its scene id."""
    conn = ConnectionId(connection)
    store.identify_client(conn, ClientIdentity(kind="cli", name=name))
    store.clients.named_sessions()  # the read that names it, as the menu build does
    scene_id = SceneId(f"{connection}-scene")
    store.replace_scene(conn, scene_id, [TextElement(id="t1", content="hi")])
    return scene_id


class TestAFrameComposingScenesWithDifferentOwners:
    def test_resolves_the_earliest_appearing_owner(self) -> None:
        # Two scenes, each owned by a different connection, share one frame;
        # the frame's owner is the one of the scene that appeared first.
        store, hub = HubDisplay(), Hub()
        first = _identified_scene(store, "c1", name="alpha")
        second = _identified_scene(store, "c2", name="beta")
        frame = ScenePresentation(frame_id="shared-frame")
        store.frames.record(first, frame)
        store.frames.record(second, frame)

        rows = _reader(store, hub).facts_for_frame("shared-frame")

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"

    def test_seniority_is_first_appearance_not_lexical_scene_id(self) -> None:
        # The frame first receives "z-scene" (owner "z"), then "a-scene"
        # (owner "a"). Seniority is first-appearance order, so the canonical
        # owner is "z" -- lexical scene-id order would wrongly pick "a".
        store, hub = HubDisplay(), Hub()
        senior = _identified_scene(store, "z", name="alpha")
        junior = _identified_scene(store, "a", name="beta")
        frame = ScenePresentation(frame_id="shared-frame")
        store.frames.record(senior, frame)
        store.frames.record(junior, frame)

        rows = _reader(store, hub).facts_for_frame("shared-frame")

        assert rows is not None
        assert dict(rows)["Connection"] == "z"

    def test_a_scene_shown_elsewhere_no_longer_names_the_frames_owner(self) -> None:
        store, hub = HubDisplay(), Hub()
        first = _identified_scene(store, "c1", name="alpha")
        second = _identified_scene(store, "c2", name="beta")
        store.frames.record(first, ScenePresentation(frame_id="elsewhere"))
        store.frames.record(second, ScenePresentation(frame_id="shared-frame"))

        rows = _reader(store, hub).facts_for_frame("shared-frame")

        assert rows is not None
        assert dict(rows)["Connection"] == "c2"


class TestASelfFramedScene:
    def test_reports_its_own_owner(self) -> None:
        # A scene with no recorded presentation is framed by its own id.
        store, hub = HubDisplay(), Hub()
        scene_id = _identified_scene(store, "c1", name="alpha")

        rows = _reader(store, hub).facts_for_frame(str(scene_id))

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"

    def test_a_frame_nobody_shows_reports_none(self) -> None:
        store, hub = HubDisplay(), Hub()

        assert _reader(store, hub).facts_for_frame("nobody-framed-this") is None


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
        store, hub = HubDisplay(), Hub()
        a1 = _identified_scene(store, "c1", name="alpha")
        a2 = _identified_scene(store, "c2", name="beta")
        b1 = _identified_scene(store, "c3", name="gamma")
        store.frames.record(a1, ScenePresentation(frame_id="old"))
        store.frames.record(a2, ScenePresentation(frame_id="old"))
        store.frames.record(b1, ScenePresentation(frame_id="new"))

        def reshow() -> None:
            store.frames.record(a1, ScenePresentation(frame_id="new"))

        repl, sender, _provider, _lifecycle = _replicator(
            store,
            owner_facts=_reader(store, hub),
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
        store, hub = HubDisplay(), Hub()
        s1 = _identified_scene(store, "c1", name="alpha")
        s2 = _identified_scene(store, "c2", name="beta")
        store.frames.record(s1, ScenePresentation(frame_id="a"))
        store.frames.record(s2, ScenePresentation(frame_id="shared"))
        store.frames.record(s1, ScenePresentation(frame_id="shared"))

        rows = _reader(store, hub).facts_for_frame("shared")

        assert rows is not None
        assert dict(rows)["Connection"] == "c2"

    def test_a_re_show_in_place_keeps_the_canonical_owner(self) -> None:
        store, hub = HubDisplay(), Hub()
        s1 = _identified_scene(store, "c1", name="alpha")
        s2 = _identified_scene(store, "c2", name="beta")
        store.frames.record(s1, ScenePresentation(frame_id="shared"))
        store.frames.record(s2, ScenePresentation(frame_id="shared"))
        store.frames.record(s1, ScenePresentation(frame_id="shared", title="again"))

        rows = _reader(store, hub).facts_for_frame("shared")

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"

    def test_when_the_canonical_scene_leaves_the_next_oldest_takes_over(self) -> None:
        store, hub = HubDisplay(), Hub()
        s1 = _identified_scene(store, "c1", name="alpha")
        s2 = _identified_scene(store, "c2", name="beta")
        s3 = _identified_scene(store, "c3", name="gamma")
        for scene in (s1, s2, s3):
            store.frames.record(scene, ScenePresentation(frame_id="shared"))
        store.frames.record(s1, ScenePresentation(frame_id="elsewhere"))

        rows = _reader(store, hub).facts_for_frame("shared")

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

    def __new__(cls, store: HubDisplay, hub: Hub) -> Self:
        self = super().__new__(cls)
        self._store = store
        self._replica = SceneReplica(on_scene_replaced=_ignore_stale)
        self._repl, self._sender, _provider, _lifecycle = _replicator(
            store, owner_facts=_reader(store, hub)
        )
        self._cursor = 0
        return self

    def __enter__(self) -> Self:
        self._repl.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._repl.stop()

    def resend(self, scene: SceneId) -> str | None:
        """Resend ``scene``; return the owner connection the Display then shows."""
        self._repl.mark_dirty(scene)
        deadline = time.monotonic() + 3.0
        while len(self._sender.shows) <= self._cursor:
            assert time.monotonic() < deadline, "the replicator never sent"
            time.sleep(0.005)
        for index in range(self._cursor, len(self._sender.shows)):
            self._replica.handle_framed_scene(
                SceneMessage(
                    id=self._sender.shows[index],
                    elements=cast("list[Element]", self._sender.roots[index]),
                    frame_id=self._sender.frames[index] or "",
                    frame_owner_facts=self._sender.owner_facts[index],
                ),
                owner_fd=1,
            )
        self._cursor = len(self._sender.shows)
        rows = self._replica.owner_facts_for("shared")
        return None if rows is None else dict(rows)["Connection"]


class TestTheDisplayAdoptsTheNextCanonicalOwnerWhenTheCanonicalSceneLeaves:
    """Hub replicator -> Display replica, end to end, in process."""

    @staticmethod
    def _two_scene_frame() -> tuple[HubDisplay, Hub, SceneId, SceneId]:
        store, hub = HubDisplay(), Hub()
        s1 = _identified_scene(store, "c1", name="alpha")
        s2 = _identified_scene(store, "c2", name="beta")
        store.frames.record(s1, ScenePresentation(frame_id="shared"))
        store.frames.record(s2, ScenePresentation(frame_id="shared"))
        return store, hub, s1, s2

    def test_a_blanked_canonical_scene_hands_the_frame_to_the_next_oldest(self) -> None:
        store, hub, s1, s2 = self._two_scene_frame()
        with _Pipeline(store, hub) as pipe:
            before = [pipe.resend(s1), pipe.resend(s2)]
            store.replace_scene(ConnectionId("c1"), s1, [])
            after = pipe.resend(s1)

        assert (before, after) == (["c1", "c1"], "c2")

    def test_a_moved_canonical_scene_leaves_the_frame_unknown_until_it_is_resent(
        self,
    ) -> None:
        store, hub, s1, s2 = self._two_scene_frame()
        with _Pipeline(store, hub) as pipe:
            pipe.resend(s1)
            pipe.resend(s2)
            store.frames.record(s1, ScenePresentation(frame_id="elsewhere"))
            after_move = pipe.resend(s1)
            after_resend = pipe.resend(s2)

        assert (after_move, after_resend) == (None, "c2")

    def test_a_moved_younger_scene_never_disturbs_the_frames_owner(self) -> None:
        store, hub, s1, s2 = self._two_scene_frame()
        with _Pipeline(store, hub) as pipe:
            pipe.resend(s1)
            pipe.resend(s2)
            store.frames.record(s2, ScenePresentation(frame_id="elsewhere"))
            after_move = pipe.resend(s2)

        assert after_move == "c1"
