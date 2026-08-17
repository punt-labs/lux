"""SceneOperations — render, update, and clear a caller's own scenes.

These are the Hub-owned scene mutations as a *caller* makes them. Each takes a
typed request and returns a discriminated result. The store and the replicator
are given at construction, and element decode is a connection-scoped factory the
presentation layer wires in, so the class runs against real collaborators in a
test without the process.

Every operation here is scoped: the caller owns what it writes, and reaching the
Hub at all is that connection's contact, so a show registers the caller's session
and renews its lease. Installing itself belongs to ``SceneInstaller``, which the
Hub also uses to write scenes *for* clients that are not calling — that path
registers nobody, and holding the installer rather than this class is what makes
it unable to.

A patch-style ``update`` against a quarantined scene is refused: the scene is
unchanged, so nothing about it has become safe to render
(display-crash-quarantine.md Question 2). ``render``/``install`` are the
recovery path instead — a wholesale replace is a different tree, presumed
fixed, and ``HubDisplay.replace_scene`` lifts the quarantine as part of
installing it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.ids import SceneId, Topic
from punt_lux.operations.composition_boundary import CompositionBoundary
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.scene_results import Cleared, SceneShown
from punt_lux.operations.scene_clearing import SceneClearer
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.operations.wire_tree import WireTreeDecoder

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord
    from punt_lux.operations.models.patches import UpdateRequest
    from punt_lux.operations.models.render import RenderRequest
    from punt_lux.operations.ports import DirtyMarker, ElementFactoryFor
    from punt_lux.operations.scope import Scope

__all__ = ["SceneOperations"]


@final
class SceneOperations:
    """Install, patch, and clear the calling connection's scenes in ``HubDisplay``."""

    _display: HubDisplay
    _replicator: DirtyMarker
    _hub: Hub
    _decoder: WireTreeDecoder
    _installer: SceneInstaller
    _clearer: SceneClearer
    __slots__ = (
        "_clearer",
        "_decoder",
        "_display",
        "_hub",
        "_installer",
        "_replicator",
    )

    def __new__(
        cls,
        display: HubDisplay,
        replicator: DirtyMarker,
        element_factory: ElementFactoryFor,
        hub: Hub,
    ) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._replicator = replicator
        self._hub = hub
        self._decoder = WireTreeDecoder(element_factory)
        self._installer = SceneInstaller(display, replicator)
        self._clearer = SceneClearer(display, replicator)
        return self

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Decode the wire tree in the caller's scope, install it, or reject it."""
        if isinstance(request, OpError):
            return request
        elements = self._decoder.decode(request.elements, scope.connection_id)
        if isinstance(elements, OpError):
            return elements
        return self.install(
            SceneSubmission.of(
                elements,
                request.scene_id,
                request.presentation(),
                request.frame_ttl(),
            ),
            scope=scope,
        )

    def install(
        self, submission: SceneSubmission, *, scope: Scope
    ) -> SceneShown | OpError:
        """Install a tree the caller submitted, recording its contact first.

        The shared path for the wire-decode surface (``render``) and the Hub-side
        conveniences that *construct* their tree. Showing a scene is the caller
        reaching the Hub, so the call registers the caller's session and renews its
        lease: a client that only ever shows is still a client, and stays one for
        as long as it keeps showing.
        """
        self._display.register_client(scope.connection_id)
        return self._installer.install(submission, owner=scope.connection_id)

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch to the store, or return why it was rejected.

        A quarantined target is rejected before the writer ever sees it: a patch
        is not the recovery path (only a wholesale ``render``/``install`` lifts a
        quarantine), so leaving the scene untouched and reporting why is the
        correct answer both here (the pull path — the caller learns on its very
        next write) and for any other agent subscribed to the scene (the push
        path — fanned out on the caller's own topic scope, see
        :meth:`_notify_quarantine`). Otherwise the writer keeps its ownership and
        field-legality rejections; a rejected batch leaves the store untouched.

        The quarantine check and the writer's ``apply`` share one write-lock
        hold, so the sequence "quarantine-record was None, then apply the
        patch" is atomic against a replicator-thread quarantine landing in
        between: without the shared hold, a check-then-act race silently
        converts "reject" into "accepted-but-never-rendered" the moment
        attribution quarantines the scene between the two calls.
        Publication happens after the lock is released to keep subscriber
        fan-out off the store lock. ``scene_id`` is composed against the
        caller's own connection before it ever reaches the store — the same
        choke point every write in this class already goes through — so a
        caller can only ever patch a scene it is the connection for (DES-086).
        """
        if isinstance(request, OpError):
            return request
        sid = CompositionBoundary.compose_or_reject(
            lambda: SceneId(ConnectionScopedId.compose(scope.connection_id, scene_id))
        )
        if isinstance(sid, OpError):
            return sid
        record: QuarantineRecord | None
        with self._display.write_lock():
            record = self._display.quarantine_record(sid)
            if record is None:
                writer = HubSceneWriter(self._display)
                target = SceneScope(scope.connection_id, sid)
                result = writer.apply(target, request.to_wire())
                if isinstance(result, WriteRejected):
                    # The writer's own rejection message names the composed
                    # store key via repr() (its \x1f separator is escaped
                    # text there, not the raw byte) — restate it as the
                    # caller's own raw name, the only spelling it ever chose.
                    reason = result.reason.replace(repr(str(sid)), repr(scene_id))
                    return OpError(code="rejected", reason=reason)
                self._replicator.mark_dirty(sid)
                return SceneShown(scene_id=scene_id)
        self._notify_quarantine(sid, record, scope)
        return OpError(code="rejected", reason=record.describe(scene_id))

    def _notify_quarantine(
        self, scene_id: SceneId, record: QuarantineRecord, scope: Scope
    ) -> None:
        """Publish the quarantine to the caller's own topic subscribers.

        An agent subscribed to ``scene:<id>:quarantined`` under its own
        connection learns even when it is not the one writing — the push half
        of the two reach paths (display-crash-quarantine.md Question 2).
        """
        topic = Topic(f"scene:{scene_id}:quarantined")
        self._hub.publish(scope.connection_id, topic, record.to_payload())

    def clear(self, *, scope: Scope, scene_id: str | None = None) -> Cleared | OpError:
        """Blank the caller's scenes — all, or just ``scene_id``.

        Scoped like every operation here: the clearer removes only roots this
        connection owns and reports a scene-scoped miss rather than a false
        ``cleared``.
        """
        return self._clearer.clear(scope.connection_id, scene_id)
