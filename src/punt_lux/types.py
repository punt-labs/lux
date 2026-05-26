"""Shared type aliases for cross-module callbacks."""

from __future__ import annotations

from collections.abc import Callable

from punt_lux.protocol import RemoteEventHandlerInvocation

type EmitEventFn = Callable[[RemoteEventHandlerInvocation], None]
type OnClientDisconnectedFn = Callable[[int], None]
type OnSceneReplacedFn = Callable[[list[str]], None]
