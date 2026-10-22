"""HubComposition — luxd's one wiring of its Hub singletons.

Both surfaces are built from this recipe, so what it must guarantee is that
either one asking produces the same shape: a facade over the process store, and
a Details renderer the domain dispatch can run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub import hub_display
from punt_lux.domain.hub.details_instance import hub_client_details
from punt_lux.domain.ids import ConnectionId
from punt_lux.hub_composition import HubComposition
from punt_lux.operations import Operations
from punt_lux.operations.ports import HubPorts

if TYPE_CHECKING:
    import pytest


def test_the_recipe_composes_the_facade_every_surface_calls() -> None:
    assert isinstance(HubComposition.operations(), Operations)


def test_the_ports_carry_the_hub_collaborators() -> None:
    ports = HubComposition.ports()

    assert isinstance(ports, HubPorts)
    # The element factory is per-connection, so it answers with a decoder.
    assert ports.element_factory(ConnectionId("c1")) is not None


def test_both_surfaces_are_wired_over_the_one_process_store() -> None:
    """Two roots, one Hub: each facade reads the same scenes and the same clients."""
    first = HubComposition.operations()
    second = HubComposition.operations()

    assert first.list_scenes().scenes == second.list_scenes().scenes
    assert len(first.list_clients().clients) == len(hub_display.clients.live_sessions())


def test_binding_details_installs_a_renderer_the_dispatch_can_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A real renderer refuses an unknown connection; the Null Object would not.

    The two say different things in the log, so the line distinguishes a bound
    renderer from the stand-in that is in place before any root has run.
    """
    HubComposition.bind_client_details()

    with caplog.at_level(logging.INFO):
        hub_client_details.run(ConnectionId("nobody-is-connected-as-this"))

    assert "no longer holds a session for" in caplog.text
    assert "before luxd bound its renderer" not in caplog.text
