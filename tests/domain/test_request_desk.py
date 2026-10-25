"""The request desk's surface: its asks, its manifest and its one seat, nothing else.

The exchange the ports share is the desk's own business. A test that needs to hold a
request lock, or stamp a ping, gets it from ``tests/link_access.py`` or builds an
exchange of its own: the desk does not hand it out.
"""

from __future__ import annotations

import inspect

from punt_lux.domain.hub.request_desk import RequestDesk


def _public_names(cls: type) -> set[str]:
    return {name for name, _ in inspect.getmembers(cls) if not name.startswith("_")}


class TestTheDeskHandsOutNoExchange:
    def test_the_desks_public_surface_is_its_asks_its_manifest_and_its_seat(
        self,
    ) -> None:
        assert _public_names(RequestDesk) == {"asks", "declare", "take_seat"}
