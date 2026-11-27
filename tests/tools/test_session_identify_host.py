"""session_identify -- the host an MCP session is recorded as running on.

The Hub never claims its own machine name for a caller it cannot place: a
session that declares no host is recorded as the host its transport observed,
and only a caller no transport observed (in-process, stdio) is taken to run
where the Hub runs.
"""

from __future__ import annotations

from unittest import mock

from punt_lux.commands._result import CommandResult
from punt_lux.kernel.client_host import UNOBSERVED, ClientHost
from punt_lux.kernel.local_host import LocalHost
from punt_lux.tools import write_tools
from punt_lux.tools.server import bind_session, unbind_session
from punt_lux.wire.model.client_identity import ClientIdentity


def _declared_by(*, host: str | None, peer: ClientHost) -> dict[str, object]:
    """Call the tool once and return the declaration it handed the command."""
    seen: list[dict[str, object]] = []

    async def capture(
        _ctx: object, declaration: dict[str, object], *, scope: object
    ) -> CommandResult:
        seen.append(declaration)
        return CommandResult(text="identified:x", json_data={})

    binding = bind_session("sess", peer)
    try:
        with mock.patch.object(write_tools, "session_identify_command", capture):
            write_tools.identify("mcp-session", "x", None, None, host)
    finally:
        unbind_session(binding)
    return seen[0]


def test_an_omitted_host_is_the_observed_peer() -> None:
    declaration = _declared_by(host=None, peer=ClientHost("10.0.0.9"))

    assert declaration["host"] == "10.0.0.9"


def test_a_declared_host_beats_the_observed_peer() -> None:
    declaration = _declared_by(host="okinos", peer=ClientHost("10.0.0.9"))

    assert declaration["host"] == "okinos"


def test_an_unobserved_caller_leaves_the_identity_models_own_default() -> None:
    declaration = _declared_by(host=None, peer=UNOBSERVED)

    # No host key: the identity model fills in the machine the Hub runs on, which
    # is where an in-process or stdio caller runs.
    assert "host" not in declaration
    assert ClientIdentity.model_validate(declaration).host == LocalHost.name()
