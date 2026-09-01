"""Regression: reopening a closed board frame via its menu entry.

Reproduces the bug end to end through the real production wiring — a real
``HubDisplay``/``FrameLifecycle``, a real ``SceneOperations`` install, and a
real ``QueryOperations`` — everything except the socket and the ImGui
process. A stateful fake ``DisplayPort`` stands in for those, tracking each
frame's visibility the way the real display does, so the test proves the
*resolution*, not just that a canned reply round-trips.

Before the fix, ``raise_frame`` forwarded the caller's plain local frame name
(``"beads-lux"``) straight to the display, which only ever held it under its
connection-scoped id (DES-086) — so the raise silently found nothing, and a
closed frame stayed closed. This drives the exact sequence a beads applet
click takes: render the board into a frame, have the display report that
frame closed (the user closed it), then raise it by the same local name the
menu entry carries, and assert it comes back on screen — resolved within the
caller's OWN connection, never a search across another session's frames.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.conveniences import ConvenienceOperations
from punt_lux.operations.display_control import DisplayControlOperations
from punt_lux.operations.display_reply import DisplayFault, DisplayReplied, DisplayReply
from punt_lux.operations.frame_ref import FrameRef
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_frames import FrameStates
from punt_lux.operations.models.display_write import FrameRaise
from punt_lux.operations.models.table import RenderTableRequest
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.scope import Scope

_CONNECTION = ConnectionId("c1")
_SCOPE = Scope(_CONNECTION)
_LOCAL_FRAME = "beads-lux"
_REF = FrameRef.of(_LOCAL_FRAME, scope=_SCOPE)


class _Recorder:
    """A ``DirtyMarker`` that discards every mark — this test never reads it."""

    def mark_dirty(self, scene_id: object) -> None:
        pass

    def mark_menus(self) -> None:
        pass


class _StatefulDisplay:
    """A ``DisplayPort`` standing in for a real display's frame store.

    Tracks visibility per (already-scoped) frame id, the same state a real
    display holds: ``list_scenes`` reports it, ``raise_frame`` flips a held
    frame to ``on_screen`` and refuses one it does not hold — exactly the
    contract the resolution logic depends on.
    """

    _visibility: dict[str, str]
    _last_raise_params: Mapping[str, object]
    __slots__ = ("_last_raise_params", "_visibility")

    def __new__(cls, visibility: dict[str, str]) -> Self:
        self = super().__new__(cls)
        self._visibility = visibility
        self._last_raise_params = {}
        return self

    @property
    def last_raise_params(self) -> Mapping[str, object]:
        return self._last_raise_params

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        if method == "list_scenes":
            return DisplayReplied(
                {
                    "scenes": [],
                    "frames": [
                        {
                            "frame_id": fid,
                            "title": fid,
                            "visibility": vis,
                            "scene_ids": [],
                        }
                        for fid, vis in self._visibility.items()
                    ],
                }
            )
        if method == "raise_frame":
            self._last_raise_params = params
            fid = params["frame_id"]
            if not isinstance(fid, str) or fid not in self._visibility:
                return DisplayReplied({"frame_id": fid, "raised": False})
            self._visibility[fid] = "on_screen"
            return DisplayReplied({"frame_id": fid, "raised": True})
        msg = f"unexpected query in this scenario: {method!r}"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> DisplayReply:  # pragma: no cover — unused
        return DisplayReplied({"rtt_seconds": 0.0})


def _queries(store: HubDisplay, display: _StatefulDisplay) -> QueryOperations:
    return QueryOperations(store, Hub(), display)


def test_raising_a_closed_beads_frame_by_its_local_name_restores_it() -> None:
    # Goes through the real SceneOperations/ConvenienceOperations install path,
    # not a lower-level store write, so the frame id resolved below is exactly
    # what ScenePresentation.scoped composes in production (scene_installer.py)
    # -- the id the bug's fix must resolve a caller's plain local name back to.
    store = HubDisplay()
    scenes = SceneOperations(store, _Recorder(), hub_element_factory, Hub())
    request = RenderTableRequest.parse(
        {"scene_id": _LOCAL_FRAME, "columns": ["issue"], "rows": [["beads-1"]]}
    )
    ConvenienceOperations(scenes).render_table(request, scope=_SCOPE)
    scoped_frame_id = store.frames.frame_id_for_local(
        _LOCAL_FRAME, connection=_CONNECTION
    )
    assert scoped_frame_id is not None
    assert scoped_frame_id == ConnectionScopedId.compose(_CONNECTION, _LOCAL_FRAME)

    # The user closed the frame -- the display's own fact, never told to the Hub.
    display = _StatefulDisplay({scoped_frame_id: "closed"})

    # The menu entry re-clicked: the same plain local name it always carries.
    result = _queries(store, display).raise_frame(_REF)

    assert isinstance(result, FrameRaise)
    assert result.raised is True
    assert result.frame_id == _LOCAL_FRAME  # the caller's own name comes back
    # The display was asked for the scoped id, never the bare local name --
    # this is the resolution the bug's fix adds.
    assert display.last_raise_params == {"frame_id": scoped_frame_id}

    frames = DisplayControlOperations(display).list_frames()
    assert isinstance(frames, FrameStates)
    frame = next(f for f in frames.frames if f.frame_id == scoped_frame_id)
    assert frame.visibility == "on_screen"
    assert frame.is_closed is False


def test_an_unresolvable_local_name_is_passed_through_and_refused() -> None:
    """A name this connection never showed -- no board was ever shown -- is refused.

    Unresolved names must not be guessed at: the display then answers the same
    way it would for any frame it has never heard of.
    """
    store = HubDisplay()
    display = _StatefulDisplay({})

    ref = FrameRef.of("no-such-board", scope=_SCOPE)
    result = _queries(store, display).raise_frame(ref)

    assert isinstance(result, FrameRaise)
    assert result.raised is False
    assert display.last_raise_params == {"frame_id": "no-such-board"}


def test_raise_frame_reports_op_error_when_the_display_cannot_be_reached() -> None:
    class _DownDisplay:
        def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
            return DisplayFault(code="display_unavailable")

        def ping(self, wait: float | None) -> DisplayReply:  # pragma: no cover
            return DisplayFault(code="display_unavailable")

    store = HubDisplay()
    ops = QueryOperations(store, Hub(), _DownDisplay())

    result = ops.raise_frame(_REF)

    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"


def test_two_connections_sharing_a_local_name_each_raise_only_their_own() -> None:
    """The gvr finding: ``beads-<repo>`` carries no session component.

    Two Claude sessions in the same repo each install a frame whose local
    part is identically ``"beads-lux"``, under two different connections.
    Reopening one must raise that session's own frame -- never the other's,
    and never a silent no-op from refusing to pick between them.
    """
    other = ConnectionId("c2")
    store = HubDisplay()
    scenes = SceneOperations(store, _Recorder(), hub_element_factory, Hub())
    conveniences = ConvenienceOperations(scenes)
    request = RenderTableRequest.parse(
        {"scene_id": _LOCAL_FRAME, "columns": ["issue"], "rows": [["beads-1"]]}
    )
    conveniences.render_table(request, scope=_SCOPE)
    conveniences.render_table(request, scope=Scope(other))

    mine = store.frames.frame_id_for_local(_LOCAL_FRAME, connection=_CONNECTION)
    theirs = store.frames.frame_id_for_local(_LOCAL_FRAME, connection=other)
    assert mine is not None
    assert theirs is not None
    assert mine != theirs  # DES-086: never the same store key

    # Both sessions' frames are closed; only mine gets reopened.
    display = _StatefulDisplay({mine: "closed", theirs: "closed"})

    result = _queries(store, display).raise_frame(_REF)

    assert isinstance(result, FrameRaise)
    assert result.raised is True
    assert display.last_raise_params == {"frame_id": mine}  # never theirs

    frames = DisplayControlOperations(display).list_frames()
    assert isinstance(frames, FrameStates)
    by_id = {f.frame_id: f.visibility for f in frames.frames}
    assert by_id[mine] == "on_screen"
    assert by_id[theirs] == "closed"  # untouched by my raise
