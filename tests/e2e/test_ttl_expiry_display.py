"""TTL expiry x display tier: a Hub-armed TTL removes the frame from the display.

The link-by-link pieces are unit-tested (the Hub arms and sweeps deadlines; the
display SceneManager drops a frame on an empty push). This fills the cross-tier
cell: a frame shown through the real Hub with a TTL, once the Hub's sweep retires
it, is gone from the display tier's own scene/frame state.

The Hub side is the production ``hub_display`` on its real monotonic clock, so the
TTL is short and the sweep is polled until it fires (the harness's poll-until
pattern). The empty push the sweep's blank would deliver is applied to a real
``SceneManager`` — the display tier's authoritative frame owner — and the frame
must then be gone.
"""

from __future__ import annotations

import time

import pytest

from punt_lux.domain.hub import hub, hub_display
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.protocol import SceneMessage, TextElement
from punt_lux.scene import SceneManager

_OWNER_FD = 1
_FRAME = "ttl-e2e-frame"
_SCENE = "ttl-e2e-scene"


def _framed(elements: list[TextElement]) -> SceneMessage:
    # list is invariant; the wire union admits TextElement (matches _make_scene).
    return SceneMessage(id=_SCENE, elements=elements, frame_id=_FRAME)  # type: ignore[arg-type]


@pytest.mark.integration
def test_ttl_expiry_removes_the_frame_from_the_display_tier() -> None:
    conn = ConnectionId("ttl-e2e-conn")
    scene = SceneId(_SCENE)
    leaf = TextElement(id="t", content="hi")
    display = SceneManager(on_scene_replaced=lambda _stale: None)
    try:
        # Hub tier: show the framed scene with a short TTL — real install + arm.
        hub_display.show_scene(
            conn, scene, [leaf], ScenePresentation(frame_id=_FRAME), ttl_seconds=0.05
        )
        # Display tier: the frame arrives and the SceneManager holds it.
        display.handle_framed_scene(_framed([leaf]), owner_fd=_OWNER_FD)
        assert _FRAME in display.frames

        # Hub tier: the TTL passes and the sweep retires the frame.
        deadline = time.monotonic() + 2.0
        expired: frozenset[SceneId] = frozenset()
        while time.monotonic() < deadline:
            expired = hub_display.frames.expire_due()
            if expired:
                break
            time.sleep(0.01)
        assert scene in expired  # the Hub retired the frame's scene

        # The blank the sweep drives (an empty push) crosses to the display tier.
        display.handle_framed_scene(_framed([]), owner_fd=_OWNER_FD)
        assert _FRAME not in display.frames  # the display dropped the frame
    finally:
        hub_display.frames.remove_frame(_FRAME)
        hub.on_disconnect(conn)
        hub_display.drop_connection(conn)
