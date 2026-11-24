"""SessionClaim — a session gets one applet, and the lock is what says which.

The claim is arbitrated by the kernel, so these drive the real thing: two claims
on one file, a file a dead process left behind, and four processes starting at
once. What is asserted is who may serve, never how the file looks while they
decide.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from punt_lux.applets.claim import AppletClaim, NoClaim, SessionClaim
from punt_lux.kernel.home_paths import LuxHome

# One applet, in its own process: take the claim on the path it was given, say
# what it got, and hold whatever it took until its parent closes its input.
_APPLET = """
import sys
from pathlib import Path

from punt_lux.applets.claim import SessionClaim

if sys.argv[1] == "--session":
    sys.stdin.readline()
    claim = SessionClaim.for_session("lux-beads", 7)
else:
    claim = SessionClaim(Path(sys.argv[1]))
print("taken" if claim.take() else "refused", flush=True)
sys.stdin.readline()
"""


def test_a_free_claim_is_taken(tmp_path: Path) -> None:
    assert SessionClaim(tmp_path / "lux-beads-1.pid").take() is True


def test_the_holder_writes_its_own_pid_into_the_claim(tmp_path: Path) -> None:
    """The lock arbitrates; the pid is what a person reading the file gets."""
    path = tmp_path / "lux-beads-2.pid"
    SessionClaim(path).take()

    assert path.read_text().strip().isdigit()


def test_a_second_applet_cannot_take_a_claim_that_is_held(tmp_path: Path) -> None:
    path = tmp_path / "lux-beads-3.pid"
    first = SessionClaim(path)

    assert first.take() is True
    assert SessionClaim(path).take() is False


def test_the_refused_applet_leaves_the_holder_pid_alone(tmp_path: Path) -> None:
    """A refusal writes nothing: the file still names the applet that is serving."""
    path = tmp_path / "lux-beads-4.pid"
    held = SessionClaim(path)
    held.take()
    holder = path.read_text()

    SessionClaim(path).take()

    assert path.read_text() == holder


def test_a_claim_a_dead_applet_left_behind_does_not_block_a_fresh_one(
    tmp_path: Path,
) -> None:
    """The kernel drops the lock with the holder, so a stale file is only a file.

    The pid inside it is a dead process — and could since have been recycled onto
    a live one — which is exactly why nothing reads it to decide.
    """
    path = tmp_path / "lux-beads-5.pid"
    path.write_text("999999\n")

    claim = SessionClaim(path)

    assert claim.take() is True
    assert path.read_text().strip() != "999999"


def test_a_claim_is_free_again_once_its_holder_has_gone(tmp_path: Path) -> None:
    """What the next session's applet finds after this one exits: an open field."""
    path = tmp_path / "lux-beads-6.pid"
    proc = subprocess.Popen(
        [sys.executable, "-c", _APPLET, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdin is not None
    assert proc.stdout.readline().strip() == "taken"
    proc.stdin.close()
    proc.wait(timeout=30)

    assert SessionClaim(path).take() is True


def test_only_one_of_several_applets_starting_at_once_takes_the_claim(
    tmp_path: Path,
) -> None:
    """Four processes, one session: the claim is taken once, not once per starter.

    Each holds whatever it got until this test lets it go, so all four are
    contending for the same file at the same time rather than in turn.
    """
    path = tmp_path / "lux-beads-7.pid"
    applets = [
        subprocess.Popen(
            [sys.executable, "-c", _APPLET, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    try:
        verdicts = [
            proc.stdout.readline().strip()
            for proc in applets
            if proc.stdout is not None
        ]
    finally:
        for proc in applets:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=30)

    assert verdicts.count("taken") == 1
    assert verdicts.count("refused") == 3


def test_a_session_claim_is_named_after_the_program_and_its_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Changing TMPDIR does not create a second lock for the same applet."""
    root = tmp_path / "lux"
    old_temp = tmp_path / "old"
    old_temp.mkdir()
    old_claim = old_temp / "lux-beads-4321.pid"
    old_claim.write_text("old claim\n")
    monkeypatch.setattr(LuxHome, "resolve", lambda: LuxHome(root))
    monkeypatch.setenv("TMPDIR", str(old_temp))
    monkeypatch.setattr(tempfile, "tempdir", None)

    claim = SessionClaim.for_session("lux-beads", 4321)
    assert claim.take() is True
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    assert SessionClaim.for_session("lux-beads", 4321).take() is False

    sessions = root / "sessions"
    assert stat.S_IMODE(sessions.stat().st_mode) == 0o700
    assert stat.S_IMODE((sessions / "lux-beads-4321.pid").stat().st_mode) == 0o600
    assert old_claim.read_text() == "old claim\n"


def test_concurrent_starters_resolve_one_claim_from_separate_tmpdirs(
    tmp_path: Path,
) -> None:
    applets: list[subprocess.Popen[str]] = []
    try:
        for index in range(4):
            scratch = tmp_path / f"tmp-{index}"
            scratch.mkdir()
            applets.append(
                subprocess.Popen(
                    [sys.executable, "-c", _APPLET, "--session"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                    env={**os.environ, "HOME": str(tmp_path), "TMPDIR": str(scratch)},
                )
            )
        for proc in applets:
            assert proc.stdin is not None
            proc.stdin.write("start\n")
            proc.stdin.flush()
        verdicts = [
            proc.stdout.readline().strip()
            for proc in applets
            if proc.stdout is not None
        ]
        assert sorted(verdicts) == ["refused", "refused", "refused", "taken"]
        assert (tmp_path / ".punt-labs/lux/sessions/lux-beads-7.pid").is_file()
    finally:
        for proc in applets:
            assert proc.stdin is not None
            proc.stdin.close()
            proc.wait(timeout=30)


def test_claim_refuses_a_nonprivate_session_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(LuxHome, "resolve", lambda: LuxHome(tmp_path))
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    sessions.chmod(0o755)

    with pytest.raises(PermissionError, match="session directory is not private"):
        SessionClaim.for_session("lux-beads", 4321)


def test_claim_accepts_private_sessions_under_a_setgid_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "lux"
    root.mkdir()
    root.chmod(0o2700)
    monkeypatch.setattr(LuxHome, "resolve", lambda: LuxHome(root))

    assert SessionClaim.for_session("lux-beads", 4321).take() is True
    assert (root / "sessions").stat().st_mode & 0o777 == 0o700


def test_claim_refuses_a_writable_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "lux"
    root.mkdir()
    root.chmod(0o770)
    monkeypatch.setattr(LuxHome, "resolve", lambda: LuxHome(root))

    with pytest.raises(PermissionError, match="session ancestor is writable"):
        SessionClaim.for_session("lux-beads", 4321)
    assert not (root / "sessions").exists()


def test_a_hand_run_applet_claims_nothing() -> None:
    """No session, no sibling to arbitrate against — it always serves."""
    assert NoClaim().take() is True


def test_both_claims_answer_the_same_question(tmp_path: Path) -> None:
    assert isinstance(SessionClaim(tmp_path / "lux-beads-8.pid"), AppletClaim)
    assert isinstance(NoClaim(), AppletClaim)
