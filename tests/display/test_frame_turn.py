"""FrameTurn -- the sockets' turn each frame, under one deadline, and the swap flush."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from punt_lux.display.frame_turn import FrameTurn

if TYPE_CHECKING:
    from punt_lux.display.client_queries import ClientQueries
    from punt_lux.display.client_sender import ClientSender
    from punt_lux.display.cross_host_pump import CrossHostPump
    from punt_lux.display.paint_clock import PaintClock
    from punt_lux.display.socket_server import SocketListener


class _Recorder:
    """One double for every collaborator: records the order calls arrive in."""

    calls: list[str]

    def __init__(self) -> None:
        self.calls = []

    def accept_connections(self) -> None:
        self.calls.append("accept")

    def poll_clients(self) -> None:
        self.calls.append("poll")

    def promote_connection(self, _sock: object) -> None:
        self.calls.append("promote")

    def set_frame_deadline(self, _deadline: float) -> None:
        self.calls.append("deadline-set")

    def clear_frame_deadline(self) -> None:
        self.calls.append("deadline-clear")

    def release_acks(self) -> None:
        self.calls.append("release-acks")

    def swapped(self) -> None:
        self.calls.append("swapped")

    def after_swap(self) -> None:
        self.calls.append("screenshot")

    def accept_pending(self) -> None:
        self.calls.append("accept-pending")

    def pump_ready(self) -> list[object]:
        return []

    def shutdown(self) -> None:
        self.calls.append("shutdown")


def _turn(rec: _Recorder, *, cross_host: bool = False) -> FrameTurn:
    return FrameTurn(
        sockets=cast("SocketListener", rec),
        sender=cast("ClientSender", rec),
        cross_host=cast("CrossHostPump", rec) if cross_host else None,
        paint_clock=cast("PaintClock", rec),
        queries=cast("ClientQueries", rec),
    )


class TestTheSocketsTurn:
    def test_it_accepts_pumps_and_polls_then_draws_under_one_deadline(self) -> None:
        rec = _Recorder()

        _turn(rec, cross_host=True).run(lambda: rec.calls.append("draw"))

        assert rec.calls == [
            "deadline-set",
            "accept",
            "accept-pending",
            "poll",
            "draw",
            "deadline-clear",
        ]

    def test_the_deadline_is_cleared_when_the_draw_raises(self) -> None:
        rec = _Recorder()

        def broken() -> None:
            raise RuntimeError("a frame that cannot draw")

        with pytest.raises(RuntimeError, match="cannot draw"):
            _turn(rec).run(broken)

        assert rec.calls[-1] == "deadline-clear"

    def test_with_no_cross_host_leg_nothing_is_pumped(self) -> None:
        rec = _Recorder()

        _turn(rec).run(lambda: None)

        assert "accept-pending" not in rec.calls


class TestWhatASwapReleases:
    def test_the_clock_the_held_acks_and_the_screenshot_in_that_order(self) -> None:
        rec = _Recorder()

        _turn(rec).after_swap()

        assert rec.calls == ["swapped", "release-acks", "screenshot"]


class TestShuttingDown:
    def test_it_closes_the_cross_host_leg(self) -> None:
        rec = _Recorder()

        _turn(rec, cross_host=True).shutdown()

        assert rec.calls == ["shutdown"]

    def test_with_no_cross_host_leg_it_closes_nothing(self) -> None:
        rec = _Recorder()

        _turn(rec).shutdown()

        assert rec.calls == []
