"""CliIdentity — deriving a lux invocation's identity from its context.

The resolution is a deterministic read of the working directory: an override, then
the git repository the cwd sits in, then a headless fallback. Every path is
exercised against a real filesystem — a ``.git`` marker under a temp directory —
with no live hub and no subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.cli_identity import CliIdentity

# A path with no ``.git`` in its ancestry, for the not-in-a-repository cases. The
# repo's TMPDIR is ``.tmp/`` inside this very git repo, so a temp dir always has a
# ``.git`` ancestor — the headless cases patch ``cwd`` to an out-of-repo path.
_NO_REPO = Path("/lux-headless-not-a-repo")


def _make_repo(tmp_path: Path, name: str) -> Path:
    """Create ``tmp_path/name`` with a ``.git`` directory and return its path."""
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


@pytest.fixture(autouse=True)
def clear_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ``LUX_CLIENT`` so a developer's environment never leaks into a test."""
    monkeypatch.delenv("LUX_CLIENT", raising=False)


def test_derives_name_and_repo_from_the_git_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, "vox")
    monkeypatch.chdir(repo)
    identity = CliIdentity.resolve()
    assert identity.kind == "cli"
    assert identity.name == "vox"  # the repository's directory name
    assert identity.repo == str(repo)


def test_finds_the_root_from_a_nested_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, "lux")
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    identity = CliIdentity.resolve()
    assert identity.repo == str(repo)  # the walk climbs to the repo root


def test_a_worktree_git_file_still_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A worktree's ``.git`` is a file, not a directory; exists() must catch it.
    repo = tmp_path / "wt"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /elsewhere\n")
    monkeypatch.chdir(repo)
    assert CliIdentity.resolve().repo == str(repo)


def test_headless_when_not_in_a_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: _NO_REPO))
    identity = CliIdentity.resolve()
    assert identity.name == "lux-cli"  # real and named, never anonymous
    assert identity.repo is None


def test_flag_override_names_the_client_but_repo_is_still_derived(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, "lux")
    monkeypatch.chdir(repo)
    identity = CliIdentity.resolve(override="release-bot")
    assert identity.name == "release-bot"  # the override names the client
    assert identity.repo == str(repo)  # the repo is still the git root


def test_env_override_is_used_when_no_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: _NO_REPO))
    monkeypatch.setenv("LUX_CLIENT", "ci-runner")
    identity = CliIdentity.resolve()
    assert identity.name == "ci-runner"
    assert identity.repo is None


def test_flag_beats_the_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: _NO_REPO))
    monkeypatch.setenv("LUX_CLIENT", "from-env")
    assert CliIdentity.resolve(override="from-flag").name == "from-flag"


def test_blank_override_falls_through_to_derivation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A whitespace-only override equals no override — the repo name still wins.
    repo = _make_repo(tmp_path, "quarry")
    monkeypatch.chdir(repo)
    assert CliIdentity.resolve(override="   ").name == "quarry"
