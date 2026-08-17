"""ConnectionScopedId — collision-impossibility and idempotency by construction.

Two connections cannot construct the same composed key from the identical
local id; one connection composing the identical local id twice always gets
the identical key back, so a re-show stays idempotent.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.ids import ConnectionId


def test_two_distinct_connections_compose_distinct_keys_from_one_local_id() -> None:
    a = ConnectionScopedId.compose(ConnectionId("session-a"), "music-player")
    b = ConnectionScopedId.compose(ConnectionId("session-b"), "music-player")
    assert a != b


def test_the_same_connection_composing_the_same_local_id_is_idempotent() -> None:
    first = ConnectionScopedId.compose(ConnectionId("session-a"), "music-player")
    second = ConnectionScopedId.compose(ConnectionId("session-a"), "music-player")
    assert first == second


def test_str_matches_compose() -> None:
    scoped = ConnectionScopedId(ConnectionId("session-a"), "music-player")
    assert str(scoped) == ConnectionScopedId.compose(
        ConnectionId("session-a"), "music-player"
    )


def test_a_blank_local_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ConnectionScopedId(ConnectionId("session-a"), "")


def test_a_whitespace_only_local_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ConnectionScopedId(ConnectionId("session-a"), "   ")


def test_a_local_id_carrying_the_separator_is_rejected() -> None:
    # The separator is a control character no honest caller-chosen id ever
    # contains — a local_id that carries it could not have been produced
    # honestly, since it is what a hostile process would need to embed to try
    # to forge another connection's composed key (DES-086 threat model).
    with pytest.raises(ValueError, match="unit separator"):
        ConnectionScopedId(ConnectionId("session-a"), "music\x1fplayer")


def test_from_composed_round_trips_compose() -> None:
    composed = ConnectionScopedId.compose(ConnectionId("session-a"), "music-player")
    parsed = ConnectionScopedId.from_composed(composed)
    assert parsed == ConnectionScopedId(ConnectionId("session-a"), "music-player")


def test_from_composed_rejects_a_string_that_never_went_through_compose() -> None:
    with pytest.raises(ValueError, match="not a connection-scoped id"):
        ConnectionScopedId.from_composed("music-player")


def test_local_id_of_returns_the_callers_own_name_for_a_composed_key() -> None:
    composed = ConnectionScopedId.compose(ConnectionId("session-a"), "music-player")
    assert ConnectionScopedId.local_id_of(composed) == "music-player"


def test_local_id_of_falls_back_to_the_raw_key_when_not_composed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A key installed through a lower-level API outside the composition choke
    # point carries no separator at all — the fallback reports it as-is rather
    # than raising, but the anomaly is logged, not silently absorbed (M-A).
    with caplog.at_level("WARNING"):
        assert ConnectionScopedId.local_id_of("board") == "board"
    assert "non-composed store key" in caplog.text
    assert "'board'" in caplog.text
