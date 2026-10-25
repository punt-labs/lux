"""Every reply the display makes goes through ``reply_to_client``, found structurally.

The Hub matches a reply to its request by order, so a reply the display cannot send
must end the connection (``reply_to_client``), never be deferred and forgotten
(``send_to_client`` returns ``False`` for a deferral and leaves the caller to hold
it, which only an event's sender does). The reply kinds are not listed here: they are
every message the display constructs, less the kinds its interaction sender sends.
The guard fails on planted violations, so it cannot pass by checking nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Self, final, get_args

from punt_lux.protocol.messages import DisplayMessage

_DISPLAY = Path(__file__).resolve().parents[2] / "src" / "punt_lux" / "display"
_EVENT_SENDER = "interaction_delivery"
_SENDER_HOME = ("socket_server", "reply_to_client")


@final
class ReplySiteScan:
    """Finds, in display sources, the sends and constructions that break the rule."""

    _replies: frozenset[str]
    __slots__ = ("_replies",)

    def __new__(cls, replies: frozenset[str]) -> Self:
        self = super().__new__(cls)
        self._replies = replies
        return self

    def violations(self, source: str, module: str) -> list[str]:
        """Return what ``source`` (display module ``module``) does that it must not."""
        found: list[str] = []
        tree = ast.parse(source)
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                found += self._in_function(func, module)
        if module == _EVENT_SENDER:
            found += [
                f"{module}: names the reply {name}"
                for name in sorted(self._names(tree) & self._replies)
            ]
        return found

    def _in_function(
        self, func: ast.FunctionDef | ast.AsyncFunctionDef, module: str
    ) -> list[str]:
        calls = [c for c in ast.walk(func) if isinstance(c, ast.Call)]
        called = {self._callee(c) for c in calls}
        found: list[str] = []
        if (
            "send_to_client" in called
            and module != _EVENT_SENDER
            and (module, func.name) != _SENDER_HOME
        ):
            found.append(
                f"{module}.{func.name}: send_to_client outside the event sender"
            )
        built = sorted(self._constructed(calls) & self._replies)
        returns = any(isinstance(n, ast.Return) for n in ast.walk(func))
        if built and "reply_to_client" not in called and not returns:
            found.append(
                f"{module}.{func.name}: builds {', '.join(built)}, never replies"
            )
        return found

    @staticmethod
    def _callee(call: ast.Call) -> str:
        fn = call.func
        if isinstance(fn, ast.Attribute):
            return fn.attr
        return fn.id if isinstance(fn, ast.Name) else ""

    def _constructed(self, calls: list[ast.Call]) -> set[str]:
        return {self._callee(c) for c in calls}

    @staticmethod
    def _names(tree: ast.AST) -> set[str]:
        return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _display_sources() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in _DISPLAY.rglob("*.py")}


def _constructed_names(source: str) -> set[str]:
    return {
        n.func.id
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _reply_names(sources: dict[str, str]) -> frozenset[str]:
    wire = {cls.__name__ for cls in get_args(DisplayMessage)}
    built = set[str]()
    for source in sources.values():
        built |= _constructed_names(source) & wire
    events = {
        n.id
        for n in ast.walk(ast.parse(sources[_EVENT_SENDER]))
        if isinstance(n, ast.Name)
    } & wire
    return frozenset(built - events)


class TestEveryReplySiteGoesThroughReplyToClient:
    def test_the_replies_the_display_makes_are_derived_not_listed(self) -> None:
        replies = _reply_names(_display_sources())

        assert {"AckMessage", "PongMessage", "QueryResponse"} <= replies
        assert "RemoteEventHandlerInvocation" not in replies

    def test_no_display_module_replies_any_other_way(self) -> None:
        sources = _display_sources()
        scan = ReplySiteScan(_reply_names(sources))

        offenders = [
            v for name, src in sources.items() for v in scan.violations(src, name)
        ]

        assert offenders == []


class TestTheGuardFailsOnAPlantedViolation:
    _SCAN = ReplySiteScan(frozenset({"AckMessage"}))

    def test_a_reply_sent_with_send_to_client(self) -> None:
        planted = (
            "def handle(self, sock):\n"
            "    self._socket_listener.send_to_client(sock, AckMessage(scene_id='s'))\n"
        )

        assert self._SCAN.violations(planted, "render_loop") != []

    def test_a_reply_built_and_never_sent(self) -> None:
        planted = "def handle(self, sock):\n    AckMessage(scene_id='s')\n"

        assert self._SCAN.violations(planted, "render_loop") != []

    def test_a_reply_named_by_the_event_sender(self) -> None:
        planted = (
            "def deliver(self, sock):\n    self.send_to_client(sock, AckMessage)\n"
        )

        assert self._SCAN.violations(planted, _EVENT_SENDER) != []

    def test_a_reply_sent_with_reply_to_client_is_clean(self) -> None:
        planted = (
            "def handle(self, sock):\n"
            "    self._socket_listener.reply_to_client(sock, AckMessage('s'))\n"
        )

        assert self._SCAN.violations(planted, "render_loop") == []

    def test_the_one_function_that_sends_is_reply_to_client(self) -> None:
        planted = (
            "def reply_to_client(self, sock, msg):\n"
            "    self.send_to_client(sock, msg)\n"
        )

        assert self._SCAN.violations(planted, "socket_server") == []
        assert self._SCAN.violations(planted, "render_loop") != []
