"""ToolExerciser — run an MCP tool under a recorded stub configuration.

The characterization corpus pins each tool's response by stubbing the
display-side dependencies the tool reaches through: ``DisplayPaths.is_running``
to decide whether to short-circuit, ``_get_client`` to substitute a fake
``DisplayClient`` whose methods return fixed values, and (for tools that
depend on the wall clock) ``time.time``.

The exerciser raises on any internal failure — a missing stub field, an
unknown method, or an unexpected exception inside the tool. It never
returns ``T | None``; the contract is "produce the tool's response or
raise" (PY-EH-8).

A ``setup`` dict has this shape::

    {
        "display_running": bool,                # patches DisplayPaths.is_running
        "time": float | None,                   # patches time.time when set
        "session_key": str | None,              # ContextVar override
        "client": {                             # stub DisplayClient
            "show":   {"return": "ack:s1"},     # AckMessage(scene_id=...) or None
            "update": {"return": "ack:s1"},
            "clear":  {"return": None},
            "ping":   {"return": {"ts": 1000.0, "display_ts": 1000.005}},
            "recv":   {"return": None | {...}},
            "set_menu":            {"return": None},
            "register_menu_item":  {"return": None},
            "query":  {"method": "set_theme", "result": {...}, "error": ...},
        },
    }

Every key is optional; whatever the tool does not call goes unconfigured.
Recording and replay go through the same code path so the corpus is, by
construction, replayable.
"""

from __future__ import annotations

import contextlib
import unittest.mock as mock
from collections.abc import Callable, Generator, Mapping
from typing import Any

from punt_lux import tools as tools_pkg
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    AckMessage,
    InteractionMessage,
    PongMessage,
    QueryResponse,
)
from punt_lux.tools.server import _session_key

__all__ = ["ToolCallError", "ToolExerciser"]


class ToolCallError(RuntimeError):
    """A tool produced a non-string or otherwise unrepresentable result."""


class _StubClient:
    """Stand-in for ``DisplayClient`` configured from a snapshot setup."""

    # PY-TS-14: per-method config shapes are heterogeneous (dicts, literals,
    # error strings) and are JSON-loaded from snapshot files — typing them
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
        return None

    def ping(self) -> PongMessage | None:
        cfg = self._spec.get("ping", {})
        ret = cfg.get("return")
        if ret is None:
            return None
        return PongMessage(ts=float(ret["ts"]), display_ts=float(ret["display_ts"]))

    def recv(self, timeout: float = 1.0) -> InteractionMessage | None:
        del timeout
        cfg = self._spec.get("recv", {})
        ret = cfg.get("return")
        if ret is None:
            return None
        return InteractionMessage(
            element_id=str(ret["element_id"]),
            action=str(ret["action"]),
            ts=float(ret["ts"]),
            value=ret.get("value"),
        )

    def set_menu(self, _menus: object) -> None:
        return None

    def register_menu_item(self, _item: object) -> None:
        return None

    def declare_menu_item(self, _item: object) -> None:
        return None

    def on_event(self, *_args: object, **_kwargs: object) -> None:
        return None

    def query(self, method: str, _params: object = None) -> QueryResponse | None:
        cfg = self._spec.get("query", {})
        if cfg.get("method") != method:
            msg = (
                f"stub query called for {method!r} but setup expected "
                f"{cfg.get('method')!r}"
            )
            raise ToolCallError(msg)
        if cfg.get("timeout"):
            return None
        return QueryResponse(
            method=method,
            result=cfg.get("result", {}),
            error=cfg.get("error"),
        )

    def _ack_or_none(self, key: str) -> AckMessage | None:
        cfg = self._spec.get(key, {})
        ret = cfg.get("return")
        if ret is None:
            return None
        return AckMessage(scene_id=str(ret["scene_id"]), ts=float(ret["ts"]))


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

        Raises ``ToolCallError`` if the tool name is unknown or its return
        type is not a string.
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
    @contextlib.contextmanager
    def _apply_setup(cls, setup: Mapping[str, object]) -> Generator[None]:
        running = bool(setup.get("display_running", False))
        client_spec = setup.get("client") or {}
        if not isinstance(client_spec, Mapping):
            msg = f"setup.client must be a mapping; got {type(client_spec).__name__}"
            raise ToolCallError(msg)

        stub_client = _StubClient(client_spec)
        # Tools fall into two families that look up DisplayClient through
        # different module attributes: the hand-written @mcp.tool ones go
        # through ``tools.tools._get_client``, while the @_query_tool
        # decorator in connection.py closes over ``connection._get_client``.
        # Both must be patched or the stub is bypassed for the @_query_tool
        # family (list_clients, get_display_info, etc.).
        stubs: list[contextlib.AbstractContextManager[Any]] = [
            mock.patch.object(DisplayPaths, "is_running", return_value=running),
            mock.patch("punt_lux.tools.tools._get_client", return_value=stub_client),
            mock.patch(
                "punt_lux.tools.connection._get_client", return_value=stub_client
            ),
        ]
        now = setup.get("time")
        if isinstance(now, int | float):
            stubs.append(mock.patch("punt_lux.tools.tools.time", _StubTime(float(now))))

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
    """Replacement for the ``time`` module in tools.py — only ``.time()``."""

    _now: float

    def __new__(cls, now: float) -> _StubTime:
        self = super().__new__(cls)
        self._now = now
        return self

    def time(self) -> float:
        return self._now
