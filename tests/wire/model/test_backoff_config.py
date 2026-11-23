"""BackoffConfig — the frozen clock/base/max/stability bundle RespawnBackoff reads."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.backoff_config import BackoffConfig
from punt_lux.domain.hub.crash_attribution import STABLE_INTERVAL


def test_defaults_match_the_crash_respawn_shape() -> None:
    config = BackoffConfig()
    assert config.base_delay == 1.0
    assert config.max_delay == 30.0
    assert config.stable_interval == STABLE_INTERVAL


def test_fields_round_trip() -> None:
    clock = lambda: 42.0  # noqa: E731 — a trivial stand-in clock, not worth a def
    config = BackoffConfig(
        clock=clock, base_delay=2.0, max_delay=120.0, stable_interval=5.0
    )
    assert config.clock is clock
    assert config.base_delay == 2.0
    assert config.max_delay == 120.0
    assert config.stable_interval == 5.0


def test_is_frozen() -> None:
    config = BackoffConfig()
    with pytest.raises(AttributeError):
        config.base_delay = 5.0  # type: ignore[misc]  # proving frozen=True raises
