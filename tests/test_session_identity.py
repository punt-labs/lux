"""SessionIdentity — what one ``lux mcp-serve`` process declares itself to be.

The resolution is a filesystem read like the CLI's, with one difference that
carries weight: the name carries the process, so two sessions on one repository
are two identities and therefore two Hub connections. These tests pin that
separation, the short declared lease, and the derived MCP session key.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from punt_lux.connection_identity import connection_for
from punt_lux.session_identity import SessionIdentity

# A path with no ``.git`` in its ancestry — the repo's TMPDIR is inside this git
# repo, so the headless cases patch ``cwd`` rather than using a temp directory.
_NO_REPO = Path("/lux-headless-not-a-repo")


def _make_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def test_declares_an_mcp_session_owning_the_git_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, "lux")
    monkeypatch.chdir(repo)
    identity = SessionIdentity.resolve()
    assert identity.client.kind == "mcp-session"
    assert identity.client.repo == str(repo)


def test_the_name_reads_as_tool_repository_and_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The name is what a user reads in the menu bar, in one uniform shape."""
    repo = _make_repo(tmp_path, "quarry")
    monkeypatch.chdir(repo)
    monkeypatch.setattr("punt_lux.session_identity.os.getpid", lambda: 0x2A)
    assert SessionIdentity.resolve().client.name == "lux · quarry · #2a"


def test_two_sessions_on_one_repository_are_two_connections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point of the process id: no silent takeover of another's clicks."""
    repo = _make_repo(tmp_path, "lux")
    monkeypatch.chdir(repo)
    monkeypatch.setattr("punt_lux.session_identity.os.getpid", lambda: 111)
    first = SessionIdentity.resolve()
    monkeypatch.setattr("punt_lux.session_identity.os.getpid", lambda: 222)
    second = SessionIdentity.resolve()

    assert first.client.name != second.client.name
    assert connection_for(first.client.model_dump()) != connection_for(
        second.client.model_dump()
    )


def test_declares_a_lease_short_enough_to_retire_a_dead_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(_make_repo(tmp_path, "lux"))
    ttl = SessionIdentity.resolve().client.lease_ttl
    assert ttl is not None
    # Longer than several keepalives (15s), short enough that a killed session's
    # menu entry is gone within the minute.
    assert 45.0 <= ttl <= 120.0


def test_headless_outside_a_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: _NO_REPO))
    identity = SessionIdentity.resolve()
    assert identity.client.repo is None
    assert identity.client.name == "lux · lux-session · #" + f"{os.getpid():x}"


def test_the_mcp_session_key_is_not_the_service_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The agent's tool surface and the click-servicing leg are separate sessions."""
    monkeypatch.chdir(_make_repo(tmp_path, "lux"))
    identity = SessionIdentity.resolve()
    key = identity.mcp_session_key
    assert key == f"mcp-{identity.client.name}"
    assert key != str(connection_for(identity.client.model_dump()))
    # The key is what luxd admits as a ConnectionId: printable and bounded.
    assert key.isprintable()
    assert len(key) <= 64
