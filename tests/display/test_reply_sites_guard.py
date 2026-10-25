"""Every reply the display makes reaches ``reply_to_client``, found structurally.

The Hub matches a reply to its request by order, so a reply the display cannot send
must end the connection (``reply_to_client``), never be deferred and forgotten, and
never be built and dropped. The doors are closed in the code first: ``send_to_client``
refuses anything but an event (``tests/display/test_socket_server.py``), and one
function writes a byte to a client. This guard reads the sources for the rest. The
reply kinds are not listed: they are every message the display constructs, less the
kinds its interaction sender sends. A reply is *made* by constructing one or by
calling a function that returns one (found by fixpoint, not named), and every value
so made must either go straight into ``reply_to_client`` or be returned to a caller,
which is then held to the same rule; anything else drops it or sends it another way.
The doors belong to one :class:`ClientSender`, built by the listener that owns the
sockets; a second construction anywhere in the package is a second set of doors, so
the guard counts constructions the way the other capabilities' guards do.
The guard fails on planted violations, so it cannot pass by checking nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Self, final, get_args

from punt_lux.protocol.messages import DisplayMessage
from tests.class_references import ClassReferences, aliased_constructions

_SRC = Path(__file__).resolve().parents[2] / "src"
_DISPLAY = _SRC / "punt_lux" / "display"
_SENDER = "ClientSender"
_SENDER_HOME = "src/punt_lux/display/socket_server.py"
_EVENT_SENDER = "interaction_delivery"
_DOOR_HOME = "client_sender"
_REPLY_DOOR = "reply_to_client"
_EVENT_DOOR = "send_to_client"
_TRANSMIT = "_transmit"
# The only functions of the door's home that may write a byte to a client.
_MAY_TRANSMIT = frozenset({_EVENT_DOOR, _REPLY_DOOR})

type _Func = ast.FunctionDef | ast.AsyncFunctionDef


def _functions(tree: ast.AST) -> list[_Func]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _callee(call: ast.Call) -> str:
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return fn.id if isinstance(fn, ast.Name) else ""


def _parents(root: ast.AST) -> dict[int, ast.AST]:
    return {
        id(child): node
        for node in ast.walk(root)
        for child in ast.iter_child_nodes(node)
    }


@final
class ReplyMakers:
    """The names that make a reply: its classes, and every function that returns one."""

    _names: frozenset[str]
    __slots__ = ("_names",)

    def __new__(cls, replies: frozenset[str], sources: dict[str, str]) -> Self:
        self = super().__new__(cls)
        makers = set(replies)
        funcs = [f for src in sources.values() for f in _functions(ast.parse(src))]
        grown = True
        while grown:
            grown = False
            for func in funcs:
                if func.name not in makers and cls._returns_a_reply(func, makers):
                    makers.add(func.name)
                    grown = True
        self._names = frozenset(makers)
        return self

    @property
    def names(self) -> frozenset[str]:
        """Every class and function whose call makes a reply."""
        return self._names

    @staticmethod
    def _returns_a_reply(func: _Func, makers: set[str]) -> bool:
        bound = _reply_vars(func, makers)
        return any(
            isinstance(n, ast.Return)
            and n.value is not None
            and _holds_a_reply(n.value, makers, bound)
            for n in ast.walk(func)
        )


def _holds_a_reply(expr: ast.AST, makers: set[str], bound: set[str]) -> bool:
    """Whether ``expr`` is, or holds, a made reply or a name bound to one."""
    return any(
        (isinstance(n, ast.Call) and _callee(n) in makers)
        or (isinstance(n, ast.Name) and n.id in bound)
        for n in ast.walk(expr)
    )


def _reply_vars(func: _Func, makers: set[str]) -> set[str]:
    """Names the function binds directly from a made reply."""
    bound: set[str] = set()
    for node in ast.walk(func):
        target, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Call)
            and _callee(value) in makers
        ):
            bound.add(target.id)
    return bound


@final
class ReplySiteScan:
    """Finds, in display sources, the sends and constructions that break the rule."""

    _replies: frozenset[str]
    _makers: frozenset[str]
    __slots__ = ("_makers", "_replies")

    def __new__(
        cls, replies: frozenset[str], makers: frozenset[str] | None = None
    ) -> Self:
        self = super().__new__(cls)
        self._replies = replies
        self._makers = replies if makers is None else makers
        return self

    def violations(self, source: str, module: str) -> list[str]:
        """Return what ``source`` (display module ``module``) does that it must not."""
        found: list[str] = []
        tree = ast.parse(source)
        for func in _functions(tree):
            found += self._doors(func, module)
            found += self._fates(func, module)
        if module == _EVENT_SENDER:
            found += [
                f"{module}: names the reply {name}"
                for name in sorted(self._names(tree) & self._replies)
            ]
        return found

    @staticmethod
    def _doors(func: _Func, module: str) -> list[str]:
        called = {_callee(c) for c in ast.walk(func) if isinstance(c, ast.Call)}
        found: list[str] = []
        if _EVENT_DOOR in called and module != _EVENT_SENDER:
            found.append(
                f"{module}.{func.name}: {_EVENT_DOOR} outside the event sender"
            )
        if _TRANSMIT in called and (module, func.name) not in {
            (_DOOR_HOME, name) for name in _MAY_TRANSMIT
        }:
            found.append(f"{module}.{func.name}: writes to a client outside the doors")
        return found

    def _fates(self, func: _Func, module: str) -> list[str]:
        """Every made reply must go into ``reply_to_client`` or be returned."""
        makers = set(self._makers)
        parent = _parents(func)
        bound = _reply_vars(func, makers)
        found: list[str] = []
        for call in ast.walk(func):
            if not (isinstance(call, ast.Call) and _callee(call) in makers):
                continue
            if self._lands(call, parent, func, bound, makers):
                continue
            found.append(
                f"{module}.{func.name}: {_callee(call)} is made and never replied"
            )
        return found

    @staticmethod
    def _lands(
        node: ast.AST,
        parent: dict[int, ast.AST],
        func: _Func,
        bound: set[str],
        makers: set[str],
    ) -> bool:
        """Whether the value made at ``node`` reaches a reply door or a return."""
        up = parent.get(id(node))
        while up is not None and up is not func:
            if isinstance(up, ast.Call) and _callee(up) == _REPLY_DOOR:
                return True
            if isinstance(up, ast.Return):
                return True
            if isinstance(up, ast.Assign | ast.AnnAssign):
                targets = up.targets if isinstance(up, ast.Assign) else [up.target]
                names = {t.id for t in targets if isinstance(t, ast.Name)}
                return bool(names & bound) and ReplySiteScan._var_lands(
                    names, func, makers
                )
            if isinstance(up, ast.stmt):
                return False
            up = parent.get(id(up))
        return False

    @staticmethod
    def _var_lands(names: set[str], func: _Func, makers: set[str]) -> bool:
        """Whether a name bound to a reply is handed on, or made into another reply.

        Handed on is into a door or a return. Made into another is read into the
        arguments of a call that makes a reply (a query's answer turned into the
        introspection response), and that reply is held to the rule in its turn.
        """
        for node in ast.walk(func):
            door = isinstance(node, ast.Call) and _callee(node) == _REPLY_DOOR
            ret = isinstance(node, ast.Return) and node.value is not None
            made = isinstance(node, ast.Call) and _callee(node) in makers
            if not (door or ret or made):
                continue
            used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if used & names:
                return True
        return False

    @staticmethod
    def _names(tree: ast.AST) -> set[str]:
        return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _display_sources() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in _DISPLAY.rglob("*.py")}


def _constructions_of(source: str, name: str) -> int:
    """How many calls in ``source`` build a ``name``, however it was reached."""
    return ClassReferences(source, name).constructions()


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

    def test_the_functions_that_return_a_reply_are_found_by_fixpoint(self) -> None:
        sources = _display_sources()

        makers = ReplyMakers(_reply_names(sources), sources).names

        assert "capture" in makers  # FramebufferCapture.capture returns the reply

    def test_no_display_module_replies_any_other_way(self) -> None:
        sources = _display_sources()
        replies = _reply_names(sources)
        scan = ReplySiteScan(replies, ReplyMakers(replies, sources).names)

        offenders = [
            v for name, src in sources.items() for v in scan.violations(src, name)
        ]

        assert offenders == []


class TestTheDoorsHaveOneOwner:
    def test_the_sender_is_built_once_by_the_listener_that_owns_the_sockets(
        self,
    ) -> None:
        built = {
            path.relative_to(_SRC.parent).as_posix(): count
            for path in sorted(_SRC.rglob("*.py"))
            if (count := _constructions_of(path.read_text(encoding="utf-8"), _SENDER))
        }

        assert built == {_SENDER_HOME: 1}

    def test_a_second_construction_is_counted_in_every_spelling(self) -> None:
        for planted in (
            "def f(host):\n    return ClientSender(host)\n",
            "def f(host):\n    return client_sender.ClientSender(host)\n",
            *aliased_constructions("punt_lux.display.client_sender", _SENDER),
        ):
            assert _constructions_of(planted, _SENDER) == 1, planted

    def test_an_aliased_name_that_is_not_the_sender_is_not_counted(self) -> None:
        planted = (
            "from punt_lux.display.client_sender import Other as C\n"
            "def f(host):\n    return C(host)\n"
        )

        assert _constructions_of(planted, _SENDER) == 0

    def test_a_module_that_only_annotates_the_sender_builds_none(self) -> None:
        planted = "def f(sender: ClientSender) -> None:\n    sender.go()\n"

        assert _constructions_of(planted, _SENDER) == 0


class TestTheGuardFailsOnAPlantedViolation:
    _SCAN = ReplySiteScan(frozenset({"AckMessage", "PongMessage", "QueryResponse"}))

    def test_a_reply_sent_with_send_to_client(self) -> None:
        planted = (
            "def handle(self, sock):\n"
            "    self._socket_listener.send_to_client(sock, AckMessage(scene_id='s'))\n"
        )

        assert self._SCAN.violations(planted, "render_loop") != []

    def test_a_reply_built_and_never_sent(self) -> None:
        planted = "def handle(self, sock):\n    AckMessage(scene_id='s')\n"

        assert self._SCAN.violations(planted, "render_loop") != []

    def test_a_reply_built_and_dropped_beside_an_unrelated_return(self) -> None:
        # The early ``return`` is not the reply's: it must not excuse the drop.
        planted = (
            "def _handle_ping(self, sock, msg):\n"
            "    if sock not in self._socket_listener.clients:\n"
            "        return\n"
            "    PongMessage(ts=msg.ts)\n"
        )

        assert self._SCAN.violations(planted, "render_loop") != []

    def test_a_reply_written_to_the_socket_directly(self) -> None:
        planted = (
            "def handle(self, sock):\n"
            "    sock.sendall(encode_message(QueryResponse(method='m')))\n"
            "    return None\n"
        )

        assert self._SCAN.violations(planted, "render_loop") != []

    def test_a_reply_bound_to_a_name_and_dropped(self) -> None:
        planted = (
            "def handle(self, sock, msg):\n"
            "    pong = PongMessage(ts=msg.ts)\n"
            "    self._log.debug('built %s', pong)\n"
        )

        assert self._SCAN.violations(planted, "render_loop") != []

    def test_a_reply_read_into_another_reply_that_lands_is_clean(self) -> None:
        planted = (
            "def handle(self, sock, msg):\n"
            "    answer = QueryResponse(method='m')\n"
            "    pong = PongMessage(ts=answer.ts)\n"
            "    self._socket_listener.reply_to_client(sock, pong)\n"
        )

        assert self._SCAN.violations(planted, "render_loop") == []

    def test_a_reply_a_caller_discards(self) -> None:
        makers = frozenset({"AckMessage", "PongMessage", "QueryResponse", "capture"})
        scan = ReplySiteScan(self._SCAN._replies, makers)
        planted = "def handle(self, sock):\n    self._capture.capture()\n"

        assert scan.violations(planted, "render_loop") != []

    def test_a_reply_a_caller_hands_to_the_door_is_clean(self) -> None:
        makers = frozenset({"AckMessage", "PongMessage", "QueryResponse", "capture"})
        scan = ReplySiteScan(self._SCAN._replies, makers)
        planted = (
            "def handle(self, sock):\n"
            "    self._listener.reply_to_client(sock, self._capture.capture())\n"
        )

        assert scan.violations(planted, "render_loop") == []

    def test_a_writing_of_a_byte_outside_the_doors(self) -> None:
        planted = (
            "def handle(self, sock, msg):\n    self._listener._transmit(sock, msg)\n"
        )

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

    def test_a_reply_bound_then_replied_is_clean(self) -> None:
        planted = (
            "def handle(self, sock, msg):\n"
            "    pong = PongMessage(ts=msg.ts)\n"
            "    self._socket_listener.reply_to_client(sock, pong)\n"
        )

        assert self._SCAN.violations(planted, "render_loop") == []

    def test_a_reply_returned_to_the_caller_is_clean(self) -> None:
        planted = "def capture(self):\n    return QueryResponse(method='m')\n"

        assert self._SCAN.violations(planted, "render_loop") == []

    def test_the_doors_are_the_only_functions_that_write_a_byte(self) -> None:
        planted = (
            "def reply_to_client(self, sock, msg):\n"
            "    self._transmit(sock, msg)\n"
            "def send_to_client(self, sock, msg):\n"
            "    return self._transmit(sock, msg)\n"
        )

        assert self._SCAN.violations(planted, "client_sender") == []
        assert self._SCAN.violations(planted, "render_loop") != []
