"""A pinned dial's name is process-scoped, deterministic, and not a capability."""

from __future__ import annotations

from itertools import count
from unittest.mock import MagicMock, patch

from punt_lux.hub.dial_generation import DialGeneration
from punt_lux.hub.display_requests import DisplayRequests


def test_pinned_ports_keep_one_name_and_new_dials_get_new_serials() -> None:
    with patch("punt_lux.hub.dial_generation.DialSocket"):
        first = DialGeneration(MagicMock(), MagicMock())
        second = DialGeneration(MagicMock(), MagicMock())
    first_port = DisplayRequests(first, MagicMock())
    assert first_port.connection_id == DisplayRequests(first, MagicMock()).connection_id
    assert (
        first_port.connection_id != DisplayRequests(second, MagicMock()).connection_id
    )
    assert int(second.connection_id.split(":")[-1]) > int(
        first.connection_id.split(":")[-1]
    )


def test_distinct_hub_processes_and_start_times_cannot_reuse_a_dial_name() -> None:
    names = []
    for pid, started in [(100, 10), (101, 10), (100, 11)]:
        with (
            patch("punt_lux.hub.dial_generation.DialSocket"),
            patch("punt_lux.hub.dial_identity.os.getpid", return_value=pid),
            patch("punt_lux.hub.dial_identity._HUB_STARTED", started),
            patch("punt_lux.hub.dial_identity._DIAL_SEQUENCE", count(1)),
        ):
            names.append(DialGeneration(MagicMock(), MagicMock()).connection_id)
    assert names == ["100:10:1", "101:10:1", "100:11:1"]
