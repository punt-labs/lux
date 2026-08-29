"""Smoke tests for the ``LuxClient`` facade and its accessors."""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.client import (
    CallbackAccessor,
    DisplayAccessor,
    ErrorAccessor,
    EventAccessor,
    FrameAccessor,
    LuxClient,
    MenuAccessor,
    SceneAccessor,
    SessionAccessor,
)
from punt_lux.domain.hub.client_identity import ClientIdentity


def _build_client() -> LuxClient:
    """Build a LuxClient whose transport is a MagicMock (satisfies every Protocol)."""
    identity = ClientIdentity(kind="cli", name="facade-test", repo="/w/lux")
    transport = MagicMock()
    return LuxClient(transport, identity)


def test_facade_exposes_all_shipped_accessors() -> None:
    client = _build_client()
    assert isinstance(client.scene, SceneAccessor)
    assert isinstance(client.frame, FrameAccessor)
    assert isinstance(client.menu, MenuAccessor)
    assert isinstance(client.session, SessionAccessor)
    assert isinstance(client.callback, CallbackAccessor)
    assert isinstance(client.display, DisplayAccessor)
    assert isinstance(client.event, EventAccessor)
    assert isinstance(client.error, ErrorAccessor)


def test_accessors_are_cached_per_client() -> None:
    client = _build_client()
    assert client.scene is client.scene
    assert client.display is client.display


def test_identity_and_scope_are_exposed() -> None:
    client = _build_client()
    assert client.identity.kind == "cli"
    assert client.identity.name == "facade-test"
    assert client.scope.connection_id


def test_for_identity_is_the_daemon_path() -> None:
    # ``for_identity`` requires luxd to be reachable; test just asserts the shape
    # of the classmethod exists on the facade -- reachability is covered elsewhere.
    assert callable(LuxClient.for_identity)
    assert callable(LuxClient.connect)


def test_sync_returns_the_same_transport_every_time() -> None:
    client = _build_client()
    assert client.sync is client.sync
    assert client.sync is client._transport  # not a new wrapper object


def test_public_api_exports_lux_client_only() -> None:
    # The public library API exposes LuxClient; the transport classes
    # (the private REST transport, LuxHubClient) are no longer re-exported.
    import punt_lux

    assert "LuxClient" in punt_lux.__all__
    assert "_RestTransport" not in punt_lux.__all__
    assert "LuxHubClient" not in punt_lux.__all__
