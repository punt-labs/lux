"""Per-family ops stubs the Phase B command tests compose.

One class per ops family, each returning a preset outcome the test sets at
construction; a test supplies only the outcome its own command reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.session_callback import CallbackInvocation
    from punt_lux.operations import (
        ClientList,
        FrameStatePatch,
        MenuList,
        Ok,
        OpError,
        Scope,
        SetMenuRequest,
    )
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest
    from punt_lux.operations.models.identity import Identified
    from punt_lux.operations.models.pubsub import PublishRequest, Received
    from punt_lux.operations.models.pubsub_acks import (
        Published,
        Subscribed,
        Unsubscribed,
    )
    from punt_lux.operations.models.query_errors import RecentErrors
    from punt_lux.operations.models.query_events import RecentEvents


@final
class StubFrameOps:
    """``FrameOps`` stub returning one preset outcome; records routing args."""

    # `| None`: a test supplies the outcome it reads (PY-TS-14).
    _result: Ok | OpError | None
    last_call: dict[str, object]
    __slots__ = ("_result", "last_call")

    def __new__(cls, result: Ok | OpError | None = None) -> Self:
        self = super().__new__(cls)
        self._result = result
        self.last_call = {}
        return self

    def set_frame_state(
        self, frame_id: str, patch: FrameStatePatch | OpError
    ) -> Ok | OpError:
        self.last_call = {"frame_id": frame_id, "patch": patch}
        return cast("Ok | OpError", self._result)


@final
class StubMenuOps:
    """``MenuOps`` stub returning one preset outcome per method."""

    # `| None`: each field only needs a value when the test reads it.
    _set: Ok | OpError | None
    _list: MenuList | None
    last_call: dict[str, object]
    __slots__ = ("_list", "_set", "last_call")

    def __new__(
        cls,
        set_result: Ok | OpError | None = None,
        list_result: MenuList | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._set = set_result
        self._list = list_result
        self.last_call = {}
        return self

    def set_menu(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        self.last_call = {"method": "set_menu", "request": request}
        return cast("Ok | OpError", self._set)

    def list_menus(self) -> MenuList:
        self.last_call = {"method": "list_menus"}
        return cast("MenuList", self._list)


@final
class StubSessionOps:
    """``SessionOps`` stub returning one preset outcome per method."""

    _list: ClientList | None
    _identify: Identified | OpError | None
    last_call: dict[str, object]
    __slots__ = ("_identify", "_list", "last_call")

    def __new__(
        cls,
        list_result: ClientList | None = None,
        identify_result: Identified | OpError | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._list = list_result
        self._identify = identify_result
        self.last_call = {}
        return self

    def list_clients(self) -> ClientList:
        self.last_call = {"method": "list_clients"}
        return cast("ClientList", self._list)

    def identify(
        self, declaration: dict[str, object], *, scope: Scope
    ) -> Identified | OpError:
        self.last_call = {
            "method": "identify",
            "declaration": declaration,
            "scope": scope,
        }
        return cast("Identified | OpError", self._identify)


@final
class StubCallbackOps:
    """``CallbackOps`` stub returning one preset outcome per method."""

    _register: Ok | OpError | None
    _pending: tuple[CallbackInvocation, ...]
    last_call: dict[str, object]
    __slots__ = ("_pending", "_register", "last_call")

    def __new__(
        cls,
        register_result: Ok | OpError | None = None,
        pending: tuple[CallbackInvocation, ...] = (),
    ) -> Self:
        self = super().__new__(cls)
        self._register = register_result
        self._pending = pending
        self.last_call = {}
        return self

    def register_callback(
        self, request: RegisterCallbackRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        self.last_call = {
            "method": "register_callback",
            "request": request,
            "scope": scope,
        }
        return cast("Ok | OpError", self._register)

    def pending_callbacks(self, *, scope: Scope) -> tuple[CallbackInvocation, ...]:
        self.last_call = {"method": "pending_callbacks", "scope": scope}
        return self._pending


@final
class StubTopicOps:
    """``TopicOps`` stub returning one preset outcome per method."""

    _publish: Published | None
    _subscribe: Subscribed | None
    _unsubscribe: Unsubscribed | None
    _receive: Received | None
    last_call: dict[str, object]
    __slots__ = ("_publish", "_receive", "_subscribe", "_unsubscribe", "last_call")

    def __new__(
        cls,
        publish: Published | None = None,
        subscribe: Subscribed | None = None,
        unsubscribe: Unsubscribed | None = None,
        receive: Received | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._publish = publish
        self._subscribe = subscribe
        self._unsubscribe = unsubscribe
        self._receive = receive
        self.last_call = {}
        return self

    def publish(
        self, topic: str, request: PublishRequest, *, scope: Scope
    ) -> Published:
        self.last_call = {
            "method": "publish",
            "topic": topic,
            "request": request,
            "scope": scope,
        }
        return cast("Published", self._publish)

    def subscribe(self, topic: str, *, scope: Scope) -> Subscribed:
        self.last_call = {"method": "subscribe", "topic": topic, "scope": scope}
        return cast("Subscribed", self._subscribe)

    def unsubscribe(self, topic: str, *, scope: Scope) -> Unsubscribed:
        self.last_call = {"method": "unsubscribe", "topic": topic, "scope": scope}
        return cast("Unsubscribed", self._unsubscribe)

    def receive(self, *, scope: Scope) -> Received:
        self.last_call = {"method": "receive", "scope": scope}
        return cast("Received", self._receive)


@final
class StubEventOps:
    """``EventOps`` stub returning one preset outcome."""

    _result: RecentEvents | OpError | None
    last_call: dict[str, object]
    __slots__ = ("_result", "last_call")

    def __new__(cls, result: RecentEvents | OpError | None = None) -> Self:
        self = super().__new__(cls)
        self._result = result
        self.last_call = {}
        return self

    def list_recent_events(self, count: int) -> RecentEvents | OpError:
        self.last_call = {"method": "list_recent_events", "count": count}
        return cast("RecentEvents | OpError", self._result)


@final
class StubErrorOps:
    """``ErrorOps`` stub returning one preset outcome."""

    _result: RecentErrors | OpError | None
    last_call: dict[str, object]
    __slots__ = ("_result", "last_call")

    def __new__(cls, result: RecentErrors | OpError | None = None) -> Self:
        self = super().__new__(cls)
        self._result = result
        self.last_call = {}
        return self

    def list_errors(self, count: int) -> RecentErrors | OpError:
        self.last_call = {"method": "list_errors", "count": count}
        return cast("RecentErrors | OpError", self._result)
