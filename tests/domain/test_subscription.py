"""Verify Subscription.cancel is idempotent and tracks active state."""

from __future__ import annotations

from punt_lux.domain.subscription import Subscription


def test_subscription_is_active_until_cancelled() -> None:
    calls: list[int] = []

    def on_cancel() -> None:
        calls.append(1)

    sub = Subscription(on_cancel)
    initial_active = sub.is_active
    sub.cancel()
    after_active = sub.is_active
    assert initial_active is True
    assert after_active is False
    assert calls == [1]


def test_subscription_cancel_is_idempotent() -> None:
    calls: list[int] = []

    def on_cancel() -> None:
        calls.append(1)

    sub = Subscription(on_cancel)
    sub.cancel()
    sub.cancel()  # second call is a no-op
    assert calls == [1]
