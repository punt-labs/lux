"""ToolExerciser — run an MCP tool under a recorded stub configuration.

The characterization corpus pins each tool's response by stubbing the
display-side dependencies the tool reaches through: ``DisplayPaths.is_running``
to decide whether to short-circuit, ``_get_client`` to substitute a fake
``DisplayClient`` whose methods return fixed values, and (for tools that
depend on the wall clock) ``time.time``.

The exerciser raises ``ToolCallError`` for any failure the corpus can detect
locally — unknown tool name, malformed ``setup``, a stub method called whose
spec key the scenario forgot to declare, or a tool that returned something
other than ``str``. Exceptions raised *inside* the tool function (the
production code under test) propagate unchanged so the migration PRs see
the same traceback their users would. The contract is "return the tool's
response, or surface every error loudly" (PY-EH-8 plus PL-PP-3: no
defensive try/except smothering production failure modes).

A ``setup`` dict has this shape::

    {
        "display_running": bool,                # patches DisplayPaths.is_running
        "time": float,                          # patches time.time when set
        "session_key": str,                     # ContextVar override (optional)
        "client": {                             # stub DisplayClient method specs
            "show":   {"return": {...}},        # AckMessage payload or None
            "update": {"return": {...}},
            "ping":   {"return": {...}},
            "query":  {"method": "...", "result": {...}, "error": "..."},
        },
        "inbox_event": {                        # observer payload for ``recv``
            "topic": "...",
            "payload": {...},
        },
    }

A scenario only declares the client method specs the tool will actually
call. The stub raises ``ToolCallError`` when a method is called and its key
is absent — that's the safety net against "I forgot to stub X" silently
shaping a wrong-but-stable snapshot.
"""

from __future__ import annotations

import contextlib
import unittest.mock as mock
from collections.abc import Callable, Generator, Mapping
from typing import Any, ClassVar

from punt_lux import tools as tools_pkg
from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Operations
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.ports import HubPorts
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    AckMessage,
    PongMessage,
    QueryResponse,
)
from punt_lux.protocol.messages.observer import ObserverMessage
from punt_lux.tools.server import _session_key

__all__ = ["ToolCallError", "ToolExerciser"]


class ToolCallError(Exception):
    """An exerciser-detected failure: bad setup, unstubbed call, or non-str return.

    Deliberately not a ``RuntimeError``: the display connection folds a real
    ``RuntimeError`` (a failed reconnect) into a typed ``display_unavailable``, so
    a harness signal based on ``RuntimeError`` would be swallowed there instead of
    surfacing the mis-declared stub. Basing it on ``Exception`` keeps it distinct.
    """


class _StubReplicator:
    """A no-op replicator so a tool's ``mark_dirty`` never touches the real one."""

    __slots__ = ()

    def mark_dirty(self, scene_id: object) -> None:
        """Swallow the mark — the exerciser only records the tool's response."""

    def mark_cleared(self) -> None:
        """Swallow the clear mark."""

    def mark_menus(self) -> None:
        """Swallow the menu-dirty flag."""


class _StubClient:
    """Stand-in for ``DisplayClient`` configured from a snapshot setup.

    Methods consult the scenario's ``client`` spec for their return value.
    A method invoked without a matching spec key raises
    :class:`ToolCallError` so the missing stub is surfaced loudly instead
    of returning ``None`` and producing a wrong-but-stable snapshot
    (per PY-EH-8 and PL-PP-3).

    ``_PASSTHROUGH_METHODS`` names the methods that may be called without
    a spec entry. They are confined to side effects ``_setup_apps()`` fires
    on first ``_get_client()`` invocation (declare a beads-browser menu
    item, register a callback for it). Those side effects are a constant
    overhead the corpus does not need to model; without the allowlist
    every scenario would have to declare them, which is the noisy-stub
    smell ``_require_spec`` is meant to prevent.
    """

    _PASSTHROUGH_METHODS: ClassVar[frozenset[str]] = frozenset(
        {"declare_menu_item", "on_event"}
    )

    # PY-TS-14: per-method config shapes are heterogeneous (dicts, literals,
    # error strings) and JSON-loaded from snapshot files — typing them
    # precisely would require one TypedDict per tool family for no benefit
    # at the test boundary.
    _spec: Mapping[str, Mapping[str, Any]]

    def __new__(cls, spec: Mapping[str, Mapping[str, Any]]) -> _StubClient:
        self = super().__new__(cls)
        self._spec = spec
        return self

    @property
    def is_connected(self) -> bool:
        return True

    def show(self, *_args: object, **_kwargs: object) -> AckMessage | None:
        return self._ack_or_none("show")

    def update(self, *_args: object, **_kwargs: object) -> AckMessage | None:
        return self._ack_or_none("update")

    def clear(self) -> None:
        self._require_spec("clear")
        return

    def ping(self, timeout: float | None = None) -> PongMessage | None:
        cfg = self._require_spec("ping")
        ret = cfg.get("return")
        if ret is None:
            return None
        return PongMessage(ts=float(ret["ts"]), display_ts=float(ret["display_ts"]))

    def set_menu(self, _menus: object) -> None:
        self._require_spec("set_menu")
        return

    def register_menu_item(self, _item: object) -> None:
        self._require_spec("register_menu_item")
        return

    def declare_menu_item(self, _item: object) -> None:
        self._require_spec("declare_menu_item")

    def on_event(self, *_args: object, **_kwargs: object) -> None:
        self._require_spec("on_event")

    def show_async(self, *_args: object, **_kwargs: object) -> None:
        # Fire-and-forget re-push. A successful ``update`` (including an
        # idempotent remove of an absent id) re-pushes the scene; the corpus
        # models that side effect as a genuine no-op — nothing to configure.
        return

    def query(self, method: str, _params: object = None) -> QueryResponse | None:
        cfg = self._require_spec("query")
        if cfg.get("method") != method:
            msg = (
                f"stub query called for {method!r} but setup expected "
                f"{cfg.get('method')!r}"
            )
            raise ToolCallError(msg)
        # A scenario that wants a query timeout declares "return": None,
        # matching the show/update/ping convention. There is no separate
        # "timeout" key.
        if "return" in cfg and cfg["return"] is None:
            return None
        return QueryResponse(
            method=method,
            result=cfg.get("result", {}),
            error=cfg.get("error"),
        )

    def _ack_or_none(self, key: str) -> AckMessage | None:
        cfg = self._require_spec(key)
        ret = cfg.get("return")
        if ret is None:
            return None
        return AckMessage(scene_id=str(ret["scene_id"]), ts=float(ret["ts"]))

    def _require_spec(self, key: str) -> Mapping[str, Any]:
        """Return the spec for ``key``, an empty mapping for passthroughs, or raise."""
        if key in self._spec:
            return self._spec[key]
        if key in self._PASSTHROUGH_METHODS:
            return {}
        msg = (
            f"stub {key!r} called but setup did not configure it; "
            "add the entry to the scenario's client spec"
        )
        raise ToolCallError(msg)


class ToolExerciser:
    """Invoke a tool function with a snapshot's configuration applied."""

    @classmethod
    def call(
        cls,
        tool: str,
        inputs: Mapping[str, object],
        setup: Mapping[str, object],
    ) -> str:
        """Return the tool's response under ``setup`` and ``inputs``.

        Raises :class:`ToolCallError` for exerciser-detected problems:
        unknown tool name, malformed ``setup``, a stub method called
        without a configured spec entry, or a non-string return from
        the tool. Exceptions raised *inside* the tool function — the
        production code being characterised — propagate unchanged so the
        traceback matches what an agent would observe in production.
        """
        fn = cls._resolve(tool)
        with cls._apply_setup(setup):
            response = fn(**inputs)
        if not isinstance(response, str):
            msg = f"tool {tool!r} returned non-string: {type(response).__name__}"
            raise ToolCallError(msg)
        return response

    @classmethod
    def _resolve(cls, tool: str) -> Callable[..., object]:
        try:
            fn: object = getattr(tools_pkg, tool)
        except AttributeError as exc:
            msg = f"unknown tool: {tool!r}"
            raise ToolCallError(msg) from exc
        if not callable(fn):
            msg = f"tools.{tool} is not callable"
            raise ToolCallError(msg)
        return fn

    @classmethod
    def _hub_ports(cls, setup: Mapping[str, object]) -> HubPorts:
        """Build the Hub ports for a replay, stubbing the inbox for recv scenarios."""
        inbox_event = setup.get("inbox_event")
        inbox_empty = setup.get("inbox_empty")
        if inbox_event is None and not inbox_empty:
            return HubPorts(
                element_factory=hub_element_factory,
                ensure_writer=ensure_writer,
                next_event=next_event,
            )
        message = cls._inbox_message(inbox_event) if inbox_event is not None else None

        def _no_writer(_connection_id: ConnectionId) -> None:
            return None

        def _stub_next(
            _connection_id: ConnectionId, _timeout: float
        ) -> ObserverMessage | None:
            return message

        return HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=_no_writer,
            next_event=_stub_next,
        )

    @staticmethod
    def _inbox_message(inbox_event: object) -> ObserverMessage:
        """Build the queued event a recv scenario injects."""
        if not isinstance(inbox_event, Mapping):
            msg = (
                f"setup.inbox_event must be a mapping; got {type(inbox_event).__name__}"
            )
            raise ToolCallError(msg)
        payload_obj = inbox_event.get("payload", {})
        if not isinstance(payload_obj, Mapping):
            msg = (
                "setup.inbox_event.payload must be a mapping; "
                f"got {type(payload_obj).__name__}"
            )
            raise ToolCallError(msg)
        return ObserverMessage(
            topic=str(inbox_event["topic"]), payload=dict(payload_obj)
        )

    @classmethod
    @contextlib.contextmanager
    def _apply_setup(cls, setup: Mapping[str, object]) -> Generator[None]:
        running = bool(setup.get("display_running", False))
        client_spec = setup.get("client") or {}
        if not isinstance(client_spec, Mapping):
            msg = f"setup.client must be a mapping; got {type(client_spec).__name__}"
            raise ToolCallError(msg)

        stub_client = _StubClient(client_spec)
        # Isolate the store and replicator per call: a mutation operation writes
        # the ``HubDisplay`` and marks the replicator, so without a fresh store
        # each replay would see state the previous one left and mutate the
        # production singletons. The tools reach the operations through the
        # ``OPERATIONS`` facade they import; substituting a facade bound to a
        # fresh store keeps every replay independent while running the real
        # operations against real collaborators (decode, submission gate, writer).
        test_ops = Operations.for_store(
            HubDisplay(),
            _StubReplicator(),
            hub=hub,
            client_registry=client_registry,
            menu_registry=HubMenuRegistry(),
            ports=cls._hub_ports(setup),
            display_port=HubDisplayConnection(
                is_running=lambda: DisplayPaths().is_running(),
                clients=client_registry,
            ),
        )
        # All tools resolve the DisplayClient through the Hub-side
        # ClientRegistry singleton in ``punt_lux.domain.hub``. Patching
        # ``client_registry.get`` substitutes the stub for every tool —
        # both hand-written @mcp.tool ones and the @_query_tool decorator
        # family — without two separate patches.
        stubs: list[contextlib.AbstractContextManager[Any]] = [
            mock.patch.object(DisplayPaths, "is_running", return_value=running),
            mock.patch(
                "punt_lux.domain.hub.clients.client_registry.get",
                return_value=stub_client,
            ),
            mock.patch("punt_lux.tools.tools.OPERATIONS", test_ops),
            mock.patch("punt_lux.tools.subscribe_tools.OPERATIONS", test_ops),
        ]
        now = setup.get("time")
        if isinstance(now, int | float):
            # The connection owns the ping measurement now; a constant monotonic
            # stub makes t0 == t1, so the recorded rtt is a deterministic 0.000s
            # and the snapshot pins the format, not a runtime-varying number.
            stubs.append(
                mock.patch(
                    "punt_lux.operations.display_connection.time", _StubTime(float(now))
                )
            )

        session = setup.get("session_key")
        token = _session_key.set(str(session)) if session is not None else None
        try:
            with contextlib.ExitStack() as stack:
                for s in stubs:
                    stack.enter_context(s)
                yield
        finally:
            if token is not None:
                _session_key.reset(token)


class _StubTime:
    """A constant clock standing in for the ``time`` module in the connection.

    ``monotonic`` returns the same value on every read, so the ping measurement
    (``t1 - t0``) is a deterministic ``0.0`` under replay — the snapshot pins the
    adapter's string format, not a runtime-varying number.
    """

    _now: float

    def __new__(cls, now: float) -> _StubTime:
        self = super().__new__(cls)
        self._now = now
        return self

    def time(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._now
