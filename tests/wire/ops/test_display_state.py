"""The display-state port accepts structural implementations and typed outcomes."""

from __future__ import annotations

import pytest

from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.operations import DisplayStateSnapshot, OpError, Scope
from punt_lux.wire.operations.display_state import WidgetSnapshot
from punt_lux.wire.ops.display_state import DisplayStateOps
from tests.commands._family_stubs import StubDisplayStateOps

_SCOPE = Scope.in_process(ConnectionId("port-test"))


@pytest.mark.parametrize(
    "result",
    [
        DisplayStateSnapshot(
            scenes={"scene": WidgetSnapshot(values={"text": "hello"})}, frames=[]
        ),
        DisplayStateSnapshot(scenes={}, frames=[]),
        OpError(code="display_unavailable", reason="down"),
    ],
)
def test_structural_port_preserves_outcome_and_scope(
    result: DisplayStateSnapshot | OpError,
) -> None:
    stub = StubDisplayStateOps(get_result=result)
    assert isinstance(stub, DisplayStateOps)
    ops: DisplayStateOps = stub

    assert ops.get_display_state(scope=_SCOPE) is result
    assert stub.last_call == {"method": "get_display_state", "scope": _SCOPE}


def test_port_rejects_a_missing_query_method() -> None:
    assert not isinstance(object(), DisplayStateOps)
