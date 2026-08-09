"""The display's own attestation: a pushed scene, from arrival to first paint."""

from __future__ import annotations

import logging
import tempfile
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display import DisplayServer
from punt_lux.display.paint_clock import PaintClock
from punt_lux.protocol import FrameReader, SceneMessage, TextElement

if TYPE_CHECKING:
    import pytest

_PAINT_LOGGER = "punt_lux.display.paint_clock"


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


def _server() -> DisplayServer:
    return DisplayServer(f"{tempfile.mkdtemp(prefix='lux-')}/display.sock")


def _sock(fd: int = 42) -> MagicMock:
    sock = MagicMock()
    sock.send.side_effect = len
    sock.fileno.return_value = fd
    return sock


def _register(server: DisplayServer, sock: MagicMock) -> None:
    server._socket_server.clients.append(sock)
    server._socket_server._readers[sock.fileno()] = FrameReader()
    server._socket_server._fd_to_client[sock.fileno()] = sock


def test_a_received_scene_is_attested_at_the_swap_that_painted_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = PaintClock(_StepClock(0.02))
    with caplog.at_level(logging.INFO, logger=_PAINT_LOGGER):
        clock.received("beads-lux")
        clock.painted("beads-lux")
        clock.swapped()
    assert caplog.messages == ["paint scene=beads-lux 20 ms"]


def test_a_scene_is_attested_once_however_many_passes_follow(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = PaintClock(_StepClock(0.01))
    with caplog.at_level(logging.INFO, logger=_PAINT_LOGGER):
        clock.received("s1")
        clock.painted("s1")
        clock.swapped()
        clock.painted("s1")
        clock.swapped()
    assert len(caplog.messages) == 1


def test_a_pass_that_painted_nothing_new_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = PaintClock(_StepClock(0.01))
    with caplog.at_level(logging.INFO, logger=_PAINT_LOGGER):
        clock.received("hidden-tab")
        clock.swapped()
    assert caplog.messages == []


def test_a_scene_never_drawn_is_forgotten_rather_than_waiting_forever(
    caplog: pytest.LogCaptureFixture,
) -> None:
    step = _StepClock(0.0)
    clock = PaintClock(step)
    clock.received("hidden-tab")
    step.skip(6.0)
    clock.swapped()
    # The stamp is gone: a later paint of the same scene has nothing to report.
    with caplog.at_level(logging.INFO, logger=_PAINT_LOGGER):
        clock.painted("hidden-tab")
        clock.swapped()
    assert caplog.messages == []


def test_the_display_stamps_a_scene_when_it_arrives(
    caplog: pytest.LogCaptureFixture,
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
    with caplog.at_level(logging.INFO, logger=_PAINT_LOGGER):
        server._paint_clock.painted("s1")
        server._paint_clock.swapped()
    assert len(caplog.messages) == 1
    assert caplog.messages[0].startswith("paint scene=s1 ")


def test_the_display_marks_a_scene_painted_as_it_renders_it(
    caplog: pytest.LogCaptureFixture,
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
    with caplog.at_level(logging.INFO, logger=_PAINT_LOGGER):
        server._render_framed_scene(frame, "s1")
        server._on_after_swap()
    assert len(caplog.messages) == 1
    assert caplog.messages[0].startswith("paint scene=s1 ")
