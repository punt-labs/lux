"""DisplayStateProxy -- the Display's widget/frame state, scoped and normalized."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, final

from punt_lux.display.replica.widget_state import WidgetState
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.display_reply import DisplayFault, DisplayReplied, DisplayReply
from punt_lux.operations.display_state_proxy import DisplayStateProxy
from punt_lux.operations.models.common import OpError
from punt_lux.operations.scope import Scope

_C1 = ConnectionId("c1")
_C2 = ConnectionId("c2")
_SCOPE_1 = Scope(_C1)
_SCOPE_2 = Scope(_C2)


@final
class _StubPort:
    """A DisplayPort that returns one preset reply to every query."""

    _reply: DisplayReply
    __slots__ = ("_reply",)

    def __new__(cls, reply: DisplayReply) -> Self:
        self = super().__new__(cls)
        self._reply = reply
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        del method, params
        return self._reply

    def ping(self, wait: float | None) -> DisplayReply:
        del wait
        return self._reply


def test_snapshot_reads_the_callers_own_scene_and_frame() -> None:
    composed = ConnectionScopedId.compose(_C1, "s1")
    payload = {
        "scenes": {composed: {"count": 3.0, "label": "hi"}},
        "frames": [
            {
                "frame_id": "f1",
                "visibility": "on_screen",
                "active_tab": composed,
                "cascade_index": 0,
            }
        ],
    }
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot(_SCOPE_1)

    assert not isinstance(result, OpError)
    assert result.scenes["s1"].values == {"count": 3.0, "label": "hi"}
    assert result.frames[0].frame_id == "f1"
    assert result.frames[0].active_tab == "s1"


def test_snapshot_normalizes_a_composed_scene_id_to_the_callers_local_id() -> None:
    composed = ConnectionScopedId.compose(_C1, "my-scene")
    payload = {
        "scenes": {composed: {}},
        "frames": [
            {
                "frame_id": "f1",
                "visibility": "docked",
                "active_tab": composed,
                "cascade_index": 0,
            }
        ],
    }
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot(_SCOPE_1)

    assert not isinstance(result, OpError)
    assert list(result.scenes) == ["my-scene"]
    assert result.frames[0].active_tab == "my-scene"


def test_snapshot_excludes_a_scene_owned_by_another_connection() -> None:
    # The security boundary: another connection's widget values (a typed
    # password, a chosen color) must never reach a caller who does not own
    # the scene, even though the display's one flat reply holds it too.
    mine = ConnectionScopedId.compose(_C1, "mine")
    theirs = ConnectionScopedId.compose(_C2, "theirs")
    payload = {
        "scenes": {
            mine: {"a": 1.0},
            theirs: {"secret": "typed-password"},
        },
        "frames": [],
    }
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot(_SCOPE_1)

    assert not isinstance(result, OpError)
    assert list(result.scenes) == ["mine"]


def test_snapshot_never_drops_a_scene_when_two_connections_share_a_local_name() -> None:
    # This is the collision the unscoped version of this proxy used to have:
    # two connections independently choosing the identical local scene name
    # ("chart") used to land in one unscoped dict and overwrite each other.
    # Scoping by connection closes it structurally -- each caller still sees
    # its own "chart" untouched, whichever order the wire payload lists them.
    mine = ConnectionScopedId.compose(_C1, "chart")
    theirs = ConnectionScopedId.compose(_C2, "chart")
    payload = {
        "scenes": {mine: {"who": "c1"}, theirs: {"who": "c2"}},
        "frames": [],
    }
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    as_c1 = proxy.snapshot(_SCOPE_1)
    as_c2 = proxy.snapshot(_SCOPE_2)

    assert not isinstance(as_c1, OpError)
    assert not isinstance(as_c2, OpError)
    assert as_c1.scenes["chart"].values == {"who": "c1"}
    assert as_c2.scenes["chart"].values == {"who": "c2"}


def test_snapshot_hides_an_active_tab_owned_by_another_connection() -> None:
    theirs = ConnectionScopedId.compose(_C2, "theirs")
    payload = {
        "scenes": {},
        "frames": [
            {
                "frame_id": "f1",
                "visibility": "on_screen",
                "active_tab": theirs,
                "cascade_index": 0,
            }
        ],
    }
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot(_SCOPE_1)

    assert not isinstance(result, OpError)
    # The frame itself is still reported (positioning is not scene content);
    # only the foreign scene id it names is hidden.
    assert result.frames[0].frame_id == "f1"
    assert result.frames[0].active_tab is None


def test_snapshot_drops_a_non_composed_store_key_rather_than_attribute_it() -> None:
    # A key installed through a lower-level API directly carries no separator
    # (DES-086 invariant violation, logged elsewhere) -- unattributable to any
    # connection, so it is excluded rather than guessed at.
    payload = {"scenes": {"legacy-key": {"x": 1.0}}, "frames": []}
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot(_SCOPE_1)

    assert not isinstance(result, OpError)
    assert result.scenes == {}


def test_snapshot_preserves_none_active_tab_as_no_scenes_shown() -> None:
    payload = {
        "scenes": {},
        "frames": [
            {
                "frame_id": "f1",
                "visibility": "closed",
                "active_tab": None,
                "cascade_index": 0,
            }
        ],
    }
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot(_SCOPE_1)

    assert not isinstance(result, OpError)
    assert result.frames[0].active_tab is None


def test_snapshot_passes_through_a_display_fault_as_an_operror() -> None:
    proxy = DisplayStateProxy(_StubPort(DisplayFault(code="display_unavailable")))

    result = proxy.snapshot(_SCOPE_1)

    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"


def test_snapshot_rejects_a_malformed_payload_as_an_operror() -> None:
    proxy = DisplayStateProxy(
        _StubPort(DisplayReplied(payload={"scenes": "not-a-dict"}))
    )

    result = proxy.snapshot(_SCOPE_1)

    assert isinstance(result, OpError)


def test_snapshot_rejects_a_reply_that_omits_the_frames_key() -> None:
    # The display-side handler always emits both keys; an omitted one is a
    # producer/version-skew bug and must fault, not silently decode as empty.
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload={"scenes": {}})))

    result = proxy.snapshot(_SCOPE_1)

    assert isinstance(result, OpError)


def test_snapshot_rejects_a_reply_that_omits_the_scenes_key() -> None:
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload={"frames": []})))

    result = proxy.snapshot(_SCOPE_1)

    assert isinstance(result, OpError)


def test_snapshot_decodes_the_rgba_tuple_the_display_actually_emits() -> None:
    # End to end: the real Display-side producer (WidgetState.observable_snapshot,
    # not a hand-typed payload) emits a color's RGBA tuple[float, ...] -- this
    # must decode Hub-side without a ValidationError, or the two WireScalar
    # definitions (display/replica/widget_state.py and this module's) have
    # drifted apart again.
    state = WidgetState()
    state.set("swatch", (0.1, 0.2, 0.3, 1.0))
    composed = ConnectionScopedId.compose(_C1, "s1")
    payload = {"scenes": {composed: state.observable_snapshot()}, "frames": []}
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot(_SCOPE_1)

    assert not isinstance(result, OpError)
    assert result.scenes["s1"].values == {"swatch": (0.1, 0.2, 0.3, 1.0)}
