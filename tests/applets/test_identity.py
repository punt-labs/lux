"""AppletIdentity — what one applet declares itself to be.

The resolution is a filesystem read like the CLI's, with two differences that
carry weight: the name carries the session, so two sessions on one repository
are two identities and therefore two Hub connections, and it carries the
program, so two applets in one session are two identities too. These tests
pin both separations and the short declared lease.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.applets.identity import AppletIdentity
from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.applet_name_format import session_pid_of
from punt_lux.domain.hub.client_identity import ClientIdentity

# A path with no ``.git`` in its ancestry — the repo's TMPDIR is inside this git
# repo, so the headless cases patch ``cwd`` rather than using a temp directory.
_NO_REPO = Path("/lux-headless-not-a-repo")


def _make_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def test_declares_an_applet_owning_the_git_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, "lux")
    monkeypatch.chdir(repo)
    identity = AppletIdentity.for_session("lux-beads", 42)
    assert identity.client.kind == "applet"
    assert identity.client.repo == str(repo)


def test_the_name_reads_as_tool_repository_session_and_program(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The name is what a user reads in the menu bar, in one uniform shape."""
    monkeypatch.chdir(_make_repo(tmp_path, "quarry"))
    identity = AppletIdentity.for_session("lux-beads", 0x2A)
    assert identity.client.name == "lux · quarry · #2a · lux-beads"


def test_two_sessions_on_one_repository_are_two_connections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point of the session id: no silent takeover of another's clicks."""
    monkeypatch.chdir(_make_repo(tmp_path, "lux"))
    first = AppletIdentity.for_session("lux-beads", 111)
    second = AppletIdentity.for_session("lux-beads", 222)

    assert first.client.name != second.client.name
    assert connection_for(first.client.model_dump()) != connection_for(
        second.client.model_dump()
    )


def test_two_programs_in_one_session_are_two_connections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The sibling collision: two applets alive under one session, one repo.

    Without the program token both derive identity from ``(repo, session_pid)``
    alone and collapse onto the same connection — whichever registers its
    callback later silently takes over the earlier one's menu entry.
    """
    monkeypatch.chdir(_make_repo(tmp_path, "lux"))
    beads = AppletIdentity.for_session("lux-beads", 12345)
    vox_panel = AppletIdentity.for_session("vox-panel", 12345)

    assert beads.client.name != vox_panel.client.name
    assert connection_for(beads.client.model_dump()) != connection_for(
        vox_panel.client.model_dump()
    )


def test_one_session_restarted_is_the_same_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An applet restarted against a live session takes its own entry back.

    The identity follows the session rather than the applet process, so a
    respawn is a succession the Hub already knows how to handle, not a second
    entry beside the first.
    """
    monkeypatch.chdir(_make_repo(tmp_path, "lux"))
    first = AppletIdentity.for_session("lux-beads", 111)
    respawned = AppletIdentity.for_session("lux-beads", 111)

    assert connection_for(first.client.model_dump()) == connection_for(
        respawned.client.model_dump()
    )


def test_declares_a_lease_short_enough_to_retire_a_dead_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(_make_repo(tmp_path, "lux"))
    ttl = AppletIdentity.for_session("lux-beads", 1).client.lease_ttl
    assert ttl is not None
    # Longer than several keepalives (15s), short enough that a killed session's
    # menu entry is gone within the minute.
    assert 45.0 <= ttl <= 120.0


def test_headless_outside_a_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: _NO_REPO))
    identity = AppletIdentity.for_session("lux-beads", 0x1F)
    assert identity.client.repo is None
    assert identity.client.name == "lux · lux-session · #1f · lux-beads"


def test_empty_program_is_rejected() -> None:
    """An empty program would recreate the collision the field exists to prevent."""
    with pytest.raises(ValueError, match="non-empty"):
        AppletIdentity.for_session("", 12345)


@pytest.mark.parametrize("program", ["   ", "\t"])
def test_whitespace_only_program_is_rejected(program: str) -> None:
    """Whitespace strips to empty, so it is the same collision as an empty string."""
    with pytest.raises(ValueError, match="non-empty"):
        AppletIdentity.for_session(program, 12345)


def test_nul_in_program_is_rejected() -> None:
    """A NUL would break connection_for's field-joining invariant."""
    with pytest.raises(ValueError, match="NUL"):
        AppletIdentity.for_session("lux\x00beads", 12345)


def test_program_leading_trailing_whitespace_is_stripped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Accidental whitespace around a program label must not fork its identity."""
    monkeypatch.chdir(_make_repo(tmp_path, "lux"))
    padded = AppletIdentity.for_session("  beads  ", 42)
    bare = AppletIdentity.for_session("beads", 42)

    assert padded.client.name == bare.client.name
    assert connection_for(padded.client.model_dump()) == connection_for(
        bare.client.model_dump()
    )


class TestSessionPidRoundTrip:
    """The pid the constructor embeds is the pid the parser recovers.

    The parser is coupled to the ``name`` format the constructor writes: a
    change to either half must land with the matching change to the other,
    or these tests fail. They pin the coupling the grouping composer relies
    on to say two applets belong to one session.
    """

    def test_recovers_the_pid_the_constructor_embedded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(_make_repo(tmp_path, "lux"))
        identity = AppletIdentity.for_session("lux-beads", 12345)

        assert session_pid_of(identity.client) == 12345

    def test_recovers_the_pid_across_the_full_hex_range(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The pid embeds as hex, so a large value must round-trip too."""
        monkeypatch.chdir(_make_repo(tmp_path, "lux"))
        identity = AppletIdentity.for_session("lux-beads", 0xDEADBEEF)

        assert session_pid_of(identity.client) == 0xDEADBEEF

    def test_a_non_applet_has_no_session_pid(self) -> None:
        """Only an applet is named ``lux · <repo> · #<pid> · <program>``."""
        for kind in ("mcp-session", "cli", "app"):
            client = ClientIdentity(kind=kind, name="not-an-applet")
            assert session_pid_of(client) is None

    def test_a_malformed_applet_name_has_no_session_pid(self) -> None:
        """An unparseable applet name falls back to per-connection grouping."""
        malformed = ClientIdentity(kind="applet", name="not-four-parts", repo="/w/lux")
        assert session_pid_of(malformed) is None

    def test_a_non_hex_pid_has_no_session_pid(self) -> None:
        """The pid must be hex; a non-hex value contributes no grouping."""
        malformed = ClientIdentity(
            kind="applet",
            name="lux · lux · #xyz · lux-beads",
            repo="/w/lux",
        )
        assert session_pid_of(malformed) is None
