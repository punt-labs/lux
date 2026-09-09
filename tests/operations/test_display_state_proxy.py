"""DisplayStateProxy -- the Display's widget/frame state, narrowed and normalized."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.display_reply import DisplayFault, DisplayReplied, DisplayReply
from punt_lux.operations.display_state_proxy import DisplayStateProxy
from punt_lux.operations.models.common import OpError


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


def test_snapshot_reads_scenes_and_frames_from_the_payload() -> None:
    payload = {
        "scenes": {"s1": {"count": 3.0, "label": "hi"}},
        "frames": [
            {
                "frame_id": "f1",
                "visibility": "on_screen",
                "active_tab": "s1",
                "cascade_index": 0,
            }
        ],
    }
    proxy = DisplayStateProxy(_StubPort(DisplayReplied(payload=payload)))

    result = proxy.snapshot()

    assert not isinstance(result, OpError)
    assert result.scenes["s1"].values == {"count": 3.0, "label": "hi"}
    assert result.frames[0].frame_id == "f1"
    assert result.frames[0].active_tab == "s1"


def test_snapshot_normalizes_a_composed_scene_id_to_the_callers_local_id() -> None:
    composed = ConnectionScopedId.compose(ConnectionId("c1"), "my-scene")
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

    result = proxy.snapshot()

    assert not isinstance(result, OpError)
    assert list(result.scenes) == ["my-scene"]
    assert result.frames[0].active_tab == "my-scene"


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

    result = proxy.snapshot()

    assert not isinstance(result, OpError)
    assert result.frames[0].active_tab is None


def test_snapshot_passes_through_a_display_fault_as_an_operror() -> None:
    proxy = DisplayStateProxy(_StubPort(DisplayFault(code="display_unavailable")))

    result = proxy.snapshot()

    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"


def test_snapshot_rejects_a_malformed_payload_as_an_operror() -> None:
    proxy = DisplayStateProxy(
        _StubPort(DisplayReplied(payload={"scenes": "not-a-dict"}))
    )

    result = proxy.snapshot()

    assert isinstance(result, OpError)
