"""The display's own attestation: a pushed scene, from arrival to first paint."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, Mock

import pytest

from punt_lux.display import RenderLoop
from punt_lux.display.paint_clock import PaintClock
from punt_lux.protocol import FrameReader, SceneMessage, TextElement


@pytest.fixture
def record(monkeypatch: pytest.MonkeyPatch) -> Mock:
    recorder = Mock()
    monkeypatch.setattr("punt_lux.display.paint_telemetry.record_first_paint", recorder)
    return recorder


class _StepClock:
    """A clock that advances a fixed number of seconds on every reading."""

    def __init__(self, step: float) -> None:
        self._step = step
        self._now = 0.0

    def __call__(self) -> float:
        now = self._now
        self._now += self._step
        return now

    def skip(self, seconds: float) -> None:
        """Jump the clock forward, as a display left alone between passes does."""
        self._now += seconds


def _server() -> RenderLoop:
    return RenderLoop(f"{tempfile.mkdtemp(prefix='lux-')}/display.sock")


def _sock(fd: int = 42) -> MagicMock:
    sock = MagicMock()
    sock.send.side_effect = len
    sock.fileno.return_value = fd
    return sock


def _register(server: RenderLoop, sock: MagicMock) -> None:
    """Attach ``sock`` as a client identified as ``kind="hub"``.

    Every test in this module installs a scene, which requires an identified Hub.
    """
    server._socket_listener.clients.append(sock)
    server._socket_listener._registry._readers[sock.fileno()] = FrameReader()
    server._socket_listener._registry._fd_to_client[sock.fileno()] = sock
    server._socket_listener.register_client_identity(
        sock.fileno(), kind="hub", name="test-hub", connect_time=0.0
    )


def test_a_received_scene_is_attested_at_the_swap_that_painted_it() -> None:
    clock = PaintClock(_StepClock(0.02))
    clock.received("beads-lux")
    clock.painted("beads-lux")
    assert clock.swapped() == (20.0,)


def test_a_scene_is_attested_once_however_many_passes_follow() -> None:
    clock = PaintClock(_StepClock(0.01))
    clock.received("s1")
    clock.painted("s1")
    assert len(clock.swapped()) == 1
    clock.painted("s1")
    assert clock.swapped() == ()


def test_a_pass_that_painted_nothing_new_says_nothing() -> None:
    clock = PaintClock(_StepClock(0.01))
    clock.received("hidden-tab")
    assert clock.swapped() == ()


def test_a_scene_never_drawn_is_forgotten_rather_than_waiting_forever() -> None:
    step = _StepClock(0.0)
    clock = PaintClock(step)
    clock.received("hidden-tab")
    step.skip(6.0)
    clock.swapped()
    # The stamp is gone: a later paint of the same scene has nothing to report.
    clock.painted("hidden-tab")
    assert clock.swapped() == ()


def test_the_display_stamps_a_scene_when_it_arrives(
    record: Mock,
) -> None:
    """The receive leg is wired: without it, the paint below would report nothing."""
    server = _server()
    sock = _sock()
    _register(server, sock)
    server._handle_scene(
        sock,
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="f1"
        ),
    )
    server._turn.scene_painted("s1")
    server._turn.after_swap()
    record.assert_called_once()


def test_the_display_marks_a_scene_painted_as_it_renders_it(
    record: Mock,
) -> None:
    """The paint leg is wired inside the real render method, not just the clock."""
    server = _server()
    sock = _sock()
    _register(server, sock)
    server._handle_scene(
        sock,
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="f1"
        ),
    )
    frame = server._scenes.frames["f1"]
    # Render an emptied scene: the paint hook runs, the ImGui element paint does not.
    frame.scenes["s1"].elements.clear()
    server._render_framed_scene(frame, "s1")
    server._turn.after_swap()
    record.assert_called_once()
