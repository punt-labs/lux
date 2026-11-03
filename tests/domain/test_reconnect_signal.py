"""ReconnectSignal -- the pacing wait: a reconnect past a snapshot, or a stop."""

from __future__ import annotations

import threading

from punt_lux.domain.hub.reconnect_signal import ReconnectSignal
from punt_lux.domain.hub.reconnect_wait import ReconnectWait
from tests.domain.display_double import until


class TestTheGeneration:
    def test_it_starts_at_zero_and_rises_by_one_per_reconnect(self) -> None:
        signal = ReconnectSignal()

        signal.reconnected()
        signal.reconnected()

        assert signal.reconnect_generation == 2


class TestWaitingForAReconnect:
    def test_a_reconnect_after_the_snapshot_ends_the_wait_at_once(self) -> None:
        signal = ReconnectSignal()
        since = signal.reconnect_generation
        signal.reconnected()  # landed between the dial and the wait: not lost

        assert signal.wait_for_reconnect(ReconnectWait(since, 5.0)) is True

    def test_no_reconnect_past_the_snapshot_waits_out_the_timeout(self) -> None:
        signal = ReconnectSignal()
        signal.reconnected()

        woke = signal.wait_for_reconnect(
            ReconnectWait(signal.reconnect_generation, 0.05)
        )

        assert woke is False

    def test_a_reconnect_wakes_a_parked_waiter(self) -> None:
        signal = ReconnectSignal()
        woke: list[bool] = []
        waiter = threading.Thread(
            target=lambda: woke.append(
                signal.wait_for_reconnect(ReconnectWait(0, 30.0))
            )
        )
        waiter.start()

        signal.reconnected()

        assert until(lambda: woke == [True])
        waiter.join(timeout=2.0)


class TestAStop:
    def test_it_wakes_a_parked_waiter_before_its_timeout(self) -> None:
        signal = ReconnectSignal()
        woke: list[bool] = []
        waiter = threading.Thread(
            target=lambda: woke.append(
                signal.wait_for_reconnect(ReconnectWait(0, 30.0))
            )
        )
        waiter.start()

        signal.request_stop()

        assert until(lambda: woke == [True])
        waiter.join(timeout=2.0)

    def test_it_latches_so_a_later_wait_returns_at_once(self) -> None:
        signal = ReconnectSignal()
        signal.request_stop()

        assert signal.wait_for_reconnect(ReconnectWait(0, 30.0)) is True
