"""``ClientRegistry`` — reconnect listener restart and the DES-068 connect hook.

The original ``with_reconnect`` reconnected the socket but never
restarted the background listener. Push-mode callers (callbacks
registered via ``on_event``, ``poll_event`` blocked on
``_event_queue``) silently stopped receiving frames after the first
``OSError`` recovered by the registry — the socket was healthy, the
listener thread was dead.

``_connect_and_reconcile`` is the one choke point every fresh low-level
connect passes through (DES-068): it sends the manifest and marks the
Hub's live scenes (and the menu) dirty on whatever replicator is
attached, so a display that only just learned what the Hub holds also
gets repainted, not just told.
"""

from __future__ import annotations

from typing import Self

import pytest

from punt_lux.domain.hub.clients import ClientRegistry
from punt_lux.domain.ids import SceneId


class _FakeClient:
    """Records connect / close / start_listener / send_manifest calls."""

    connect_calls: int
    close_calls: int
    start_listener_calls: int
    manifests_sent: list[tuple[str, ...]]
    _fail_first_call: bool

    def __new__(cls, *, fail_first_call: bool = False) -> Self:
        self = super().__new__(cls)
        self.connect_calls = 0
        self.close_calls = 0
        self.start_listener_calls = 0
        self.manifests_sent = []
        self._fail_first_call = fail_first_call
        return self

    def connect(self) -> None:
        self.connect_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def start_listener(self) -> None:
        self.start_listener_calls += 1

    def send_manifest(self, scene_ids: tuple[str, ...]) -> None:
        self.manifests_sent.append(tuple(scene_ids))

    def set_fallback_handler(self, handler: object) -> None:
        """No-op — ``_setup_apps`` wires this; nothing here asserts on it."""

    @property
    def is_connected(self) -> bool:
        """Report connected the instant ``connect`` has been called once.

        ``get()`` only calls the reconcile path while disconnected; this
        keeps the fake's shape close enough to the real ``DisplayLink`` for
        that guard to behave the same way across repeated ``get()`` calls.
        """
        return self.connect_calls > 0

    @property
    def listener_active(self) -> bool:
        return self.start_listener_calls > 0


class _FakeMarker:
    """Records dirty marks the connect hook makes."""

    scenes_marked: list[SceneId]
    menu_marks: int
    __slots__ = ("menu_marks", "scenes_marked")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.scenes_marked = []
        self.menu_marks = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.scenes_marked.append(scene_id)

    def mark_menus(self) -> None:
        self.menu_marks += 1


def _install_client(registry: ClientRegistry, fake: _FakeClient) -> None:
    """Plant ``fake`` into ``registry`` so ``with_reconnect`` finds it."""
    registry._client = fake  # type: ignore[assignment]  # test-only duck type


def test_with_reconnect_restarts_listener_after_oserror() -> None:
    """A successful reconnect must restart the background listener."""
    registry = ClientRegistry()
    fake = _FakeClient()
    _install_client(registry, fake)

    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BrokenPipeError("simulated socket loss")
        return "ok"

    result = registry.with_reconnect(fn)

    assert result == "ok"
    assert fake.close_calls == 1
    assert fake.connect_calls == 1
    assert fake.start_listener_calls == 1


def test_with_reconnect_no_listener_restart_on_happy_path() -> None:
    """If ``fn`` succeeds, no reconnect cycle runs."""
    registry = ClientRegistry()
    fake = _FakeClient()
    _install_client(registry, fake)

    result = registry.with_reconnect(lambda: "ok")

    assert result == "ok"
    assert fake.close_calls == 0
    assert fake.connect_calls == 0
    assert fake.start_listener_calls == 0


def test_with_reconnect_wraps_reconnect_failure() -> None:
    """A failed reconnect raises ``RuntimeError`` chained from the original."""
    registry = ClientRegistry()

    class _UnreconnectableClient(_FakeClient):
        def connect(self) -> None:
            raise OSError("reconnect refused")

    fake = _UnreconnectableClient()
    _install_client(registry, fake)

    def fn() -> str:
        raise ConnectionResetError("simulated socket loss")

    with pytest.raises(RuntimeError, match="Reconnect failed"):
        registry.with_reconnect(fn)
    assert fake.start_listener_calls == 0


def test_with_reconnect_sends_the_manifest_on_the_fresh_connect() -> None:
    """The one choke point fires on ``with_reconnect``'s retry connect too."""
    registry = ClientRegistry()
    fake = _FakeClient()
    _install_client(registry, fake)

    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BrokenPipeError("simulated socket loss")
        return "ok"

    registry.with_reconnect(fn)

    assert fake.manifests_sent == [()]  # the singleton HubDisplay starts empty


class TestConnectAndReconcile:
    """``get()``'s lazy connect runs through the same choke point as reconnect."""

    def test_get_sends_the_manifest_on_a_fresh_connect(self) -> None:
        registry = ClientRegistry()
        fake = _FakeClient()
        _install_client(registry, fake)
        fake.connect_calls = 0  # force get() to see "not yet connected"

        registry.get()

        assert fake.connect_calls == 1
        assert fake.manifests_sent == [()]

    def test_get_marks_the_marker_dirty_on_a_fresh_connect(self) -> None:
        registry = ClientRegistry()
        marker = _FakeMarker()
        registry.attach_replicator(marker)
        fake = _FakeClient()
        _install_client(registry, fake)
        fake.connect_calls = 0

        registry.get()

        assert marker.menu_marks == 1
        assert marker.scenes_marked == []  # nothing live in a fresh HubDisplay

    def test_get_does_not_reconnect_when_already_connected(self) -> None:
        registry = ClientRegistry()
        fake = _FakeClient()
        _install_client(registry, fake)
        fake.connect_calls = 1  # already connected

        registry.get()

        assert fake.connect_calls == 1  # unchanged — no fresh connect ran
        assert fake.manifests_sent == []

    def test_null_marker_is_the_default_before_attach(self) -> None:
        """A registry with no replicator wired in still connects safely."""
        registry = ClientRegistry()
        fake = _FakeClient()
        _install_client(registry, fake)
        fake.connect_calls = 0

        registry.get()  # must not raise despite no attach_replicator call

        assert fake.manifests_sent == [()]
