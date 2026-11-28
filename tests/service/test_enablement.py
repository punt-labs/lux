"""Exercise Lux repository enablement against the real git index and worktree."""

from __future__ import annotations

import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastmcp import Client
from typer.testing import CliRunner

from punt_lux.cli.__main__ import app
from punt_lux.service.activation_file import ActivationFile
from punt_lux.service.claude_import import ClaudeImport
from punt_lux.service.display_mode_store import DisplayModeStore
from punt_lux.service.display_preference import DEFAULT_CONFIG_PATH, LEGACY_CONFIG_PATH
from punt_lux.service.enablement import Action, Enablement
from punt_lux.service.repo_activation import PERSONAL, SHARED, Checkout, Scope
from punt_lux.tools import mcp
from punt_lux.wire.operations import DisplayModeState

ROOT = Path(__file__).resolve().parents[2]


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            shutil.which("git") or "/usr/bin/git",
            "-C",
            str(root),
            "-c",
            "user.name=Lux Test",
            "-c",
            "user.email=lux@example.test",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def checkout(tmp_path: Path) -> Checkout:
    git(tmp_path, "init", "--quiet")
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    git(tmp_path, "add", ".gitignore")
    git(tmp_path, "commit", "-qm", "baseline")
    return Checkout(tmp_path)


def test_default_scope_and_both_startup_states_are_clean(
    checkout: Checkout,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    monkeypatch.chdir(checkout.root)
    home = tmp_path_factory.mktemp("lux-fake-home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{Path(sys.executable).parent}:/usr/bin:/bin")
    cli = CliRunner()
    off = subprocess.run(
        [
            shutil.which("bash") or "/bin/bash",
            str(ROOT / "plugin/hooks/session-start.sh"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert off.stdout == off.stderr == ""
    alias = home / ".claude/commands/lux.md"
    assert alias.read_bytes() == (ROOT / "plugin/commands/lux.md").read_bytes()
    assert list(alias.parent.iterdir()) == [alias]
    assert git(checkout.root, "status", "--porcelain") == ""
    for command in ("enable", "enable", "disable", "disable"):
        result = cli.invoke(app, [command])
        assert result.exit_code == 0, result.output
        assert (checkout.root / PERSONAL / "enabled").exists() == (command == "enable")
        assert (checkout.root / ".claude/settings.local.json").is_file()
        assert not (checkout.root / ".claude/settings.json").exists()
        assert git(checkout.root, "status", "--porcelain") == ""
    result = cli.invoke(app, ["enable", "--scope", "project"])
    assert result.exit_code == 0, result.output
    assert checkout.state().deciding_file == checkout.root / SHARED / "enabled"
    git(checkout.root, "add", "CLAUDE.md", ".claude/settings.json", str(SHARED))
    git(checkout.root, "commit", "-qm", "shared enablement")
    subprocess.run(
        [
            shutil.which("bash") or "/bin/bash",
            str(ROOT / "plugin/hooks/session-start.sh"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert git(checkout.root, "status", "--porcelain") == ""
    for command in ("enable", "disable", "disable", "enable", "enable"):
        result = cli.invoke(app, [command, "--scope", "project"])
        assert result.exit_code == 0, result.output
        if command == "enable":
            assert git(checkout.root, "status", "--porcelain") == ""
    for command in ("disable", "disable", "enable", "enable"):
        result = cli.invoke(app, [command])
        assert result.exit_code == 0, result.output
        assert checkout.state().enabled == (command == "enable")
        assert (checkout.root / PERSONAL / "disabled").exists() == (
            command == "disable"
        )
        assert not (checkout.root / PERSONAL / "enabled").exists()
        assert git(checkout.root, "status", "--porcelain") == ""


@pytest.mark.parametrize(
    ("markers", "enabled", "deciding"),
    [
        ((), False, SHARED / "enabled"),
        ((SHARED / "enabled",), True, SHARED / "enabled"),
        ((PERSONAL / "enabled",), True, PERSONAL / "enabled"),
        ((SHARED / "enabled", PERSONAL / "disabled"), False, PERSONAL / "disabled"),
        ((SHARED / "opt-out",), False, SHARED / "opt-out"),
        (
            (PERSONAL / "enabled", SHARED / "opt-out", PERSONAL / "disabled"),
            False,
            SHARED / "opt-out",
        ),
    ],
)
def test_effective_state(
    checkout: Checkout, markers: tuple[Path, ...], enabled: bool, deciding: Path
) -> None:
    for marker in markers:
        path = checkout.root / marker
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    result = checkout.state()
    assert result.enabled is enabled
    assert result.deciding_file == checkout.root / deciding


def test_pinned_guide_refresh_and_protected_paths(checkout: Checkout) -> None:
    update = Enablement(checkout, "project")
    update.apply("enable")
    guide = checkout.root / SHARED / "CLAUDE.md"
    guide.write_text("Version previously deposited\n")
    config = checkout.root / SHARED / "config.yaml"
    config.write_text("repository-owned\n")
    update.apply("enable")
    assert guide.read_text() == "Version previously deposited\n"
    update.apply("enable", refresh=True)
    assert (
        guide.read_bytes() == (ROOT / "src/punt_lux/service/lux-guide.md").read_bytes()
    )
    assert config.read_text() == "repository-owned\n"
    manifest = guide.with_name(".vendored-manifest")
    manifest.write_text("[]\n")
    with pytest.raises(ValueError, match="occupied"):
        update.apply("enable", refresh=True)
    update.apply("disable")
    assert guide.exists()


def test_local_refresh_updates_pinned_guide_when_project_enabled(
    checkout: Checkout,
) -> None:
    local = Enablement(checkout, "local")
    local.apply("enable")
    Enablement(checkout, "project").apply("enable")
    guide = checkout.root / PERSONAL / "CLAUDE.md"
    shared_guide = checkout.root / SHARED / "CLAUDE.md"
    guide.write_text("Pinned local version\n")
    shared_guide.write_text("Pinned project version\n")
    local.apply("enable")
    assert guide.read_text() == "Pinned local version\n"
    state = local.apply("enable", refresh=True)
    assert (
        guide.read_bytes() == (ROOT / "src/punt_lux/service/lux-guide.md").read_bytes()
    )
    assert shared_guide.read_text() == "Pinned project version\n"
    assert state.deciding_file == checkout.root / SHARED / "enabled"
    assert (checkout.root / PERSONAL / "enabled").exists()
    assert (checkout.root / "CLAUDE.local.md").read_bytes()


@pytest.mark.parametrize("previously_enabled", [False, True])
def test_local_refresh_skips_when_no_local_guide_is_imported(
    checkout: Checkout, monkeypatch: pytest.MonkeyPatch, previously_enabled: bool
) -> None:
    local = Enablement(checkout, "local")
    if previously_enabled:
        local.apply("enable")
        local.apply("disable")
    Enablement(checkout, "project").apply("enable")
    directory = checkout.root / PERSONAL
    before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    monkeypatch.chdir(checkout.root)
    result = CliRunner().invoke(app, ["enable", "--scope", "local", "--refresh"])
    assert result.exit_code == 0
    assert (
        "No active local Lux guide to refresh; guide files unchanged." in result.output
    )
    after = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    assert before == after


def test_local_enable_with_skipped_refresh_clears_disabled_marker(
    checkout: Checkout, monkeypatch: pytest.MonkeyPatch
) -> None:
    Enablement(checkout, "project").apply("enable")
    Enablement(checkout, "local").apply("disable")
    marker = checkout.root / PERSONAL / "disabled"
    assert marker.is_file()
    monkeypatch.chdir(checkout.root)
    result = CliRunner().invoke(app, ["enable", "--scope", "local", "--refresh"])
    assert result.exit_code == 0
    assert "Lux repo integration: enabled" in result.output
    assert "No active local Lux guide to refresh" in result.output
    assert not marker.exists()
    assert not (marker.parent / "CLAUDE.md").exists()
    assert not (marker.parent / ".vendored-manifest").exists()


def test_opt_out_refusal_leaves_both_scopes_untouched(checkout: Checkout) -> None:
    update = Enablement(checkout, "project")
    marker = checkout.root / SHARED / "opt-out"
    assert update.apply("disable", opt_out=True).deciding_file == marker
    scopes: tuple[Scope, ...] = ("project", "local")
    for scope in scopes:
        with pytest.raises(ValueError, match="opt-out"):
            Enablement(checkout, scope).apply("enable")
    assert list(marker.parent.iterdir()) == [marker]
    assert not (checkout.root / ".claude").exists()
    assert update.apply("enable", clear_opt_out=True).enabled
    assert not marker.exists()


def test_personal_write_refuses_tracked_and_symlinked_hosts(checkout: Checkout) -> None:
    host = checkout.root / "CLAUDE.local.md"
    target = checkout.root / "CLAUDE.md"
    target.write_text("shared\n")
    host.symlink_to(target)
    edit = Enablement(checkout, "local")
    with pytest.raises(ValueError, match="ignored and untracked"):
        edit.apply("enable")
    assert target.read_text() == "shared\n"
    host.unlink()
    host.write_text("tracked by mistake\n")
    git(checkout.root, "add", "-f", host.name)
    with pytest.raises(ValueError, match="ignored and untracked"):
        edit.apply("enable")
    assert host.read_text() == "tracked by mistake\n"


def test_display_migrates_to_local_and_worktree_writes_main_checkout(
    checkout: Checkout, tmp_path_factory: pytest.TempPathFactory
) -> None:
    git(
        checkout.root,
        "worktree",
        "add",
        "--detach",
        str(tmp_path_factory.mktemp("lux-linked")),
    )
    linked = next(
        Path(line.removeprefix("worktree "))
        for line in git(checkout.root, "worktree", "list", "--porcelain").splitlines()[
            1:
        ]
        if line.startswith("worktree ")
    )
    legacy = checkout.root / LEGACY_CONFIG_PATH
    legacy.parent.mkdir()
    original = '---\ndisplay: "y"\n---\n'
    legacy.write_text(original)
    git(checkout.root, "add", str(LEGACY_CONFIG_PATH))
    git(checkout.root, "commit", "-qm", "old display mode")
    nested = linked / "nested"
    nested.mkdir()
    mode = DisplayModeStore(str(nested)).read()
    assert mode == DisplayModeState(mode="on")
    Enablement(Checkout(linked), "local").apply("enable")
    local = checkout.root / DEFAULT_CONFIG_PATH
    assert 'display: "y"' in local.read_text()
    assert DisplayModeStore(str(nested)).write("n") is None
    assert 'display: "n"' in local.read_text()
    assert legacy.read_text() == original
    assert not (linked / DEFAULT_CONFIG_PATH).exists()
    nested.rmdir()
    assert git(checkout.root, "status", "--porcelain") == ""
    assert git(linked, "status", "--porcelain") == ""


def test_display_preference_uses_invoking_worktree_when_main_is_bare(
    checkout: Checkout, tmp_path_factory: pytest.TempPathFactory
) -> None:
    bare = tmp_path_factory.mktemp("lux-bare")
    linked = tmp_path_factory.mktemp("lux-from-bare")
    git(checkout.root, "clone", "--bare", ".", str(bare))
    git(bare, "worktree", "add", "--detach", str(linked), "HEAD")
    store = DisplayModeStore(str(linked))
    assert store.write("y") is None
    assert store.read() == DisplayModeState(mode="on")
    assert (linked / DEFAULT_CONFIG_PATH).is_file()
    assert not (bare / DEFAULT_CONFIG_PATH).exists()
    assert git(linked, "status", "--porcelain") == ""


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_invalid_settings_leave_integration_untouched(
    checkout: Checkout, action: Action
) -> None:
    update = Enablement(checkout, "project")
    if action == "disable":
        update.apply("enable")
    host = checkout.root / "CLAUDE.md"
    original = host.read_bytes() if host.exists() else None
    settings = checkout.root / ".claude/settings.json"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text('{"permissions":{"allow":false}}')
    with pytest.raises(ValueError, match="is not a list"):
        update.apply(action)
    assert (host.read_bytes() if host.exists() else None) == original
    assert checkout.state().enabled == (action == "disable")
    assert (checkout.root / SHARED / "CLAUDE.md").exists() == (action == "disable")
    assert settings.read_text() == '{"permissions":{"allow":false}}'


@pytest.mark.parametrize("eol", [b"\n", b"\r\n", b"\r"])
def test_import_preserves_user_bytes_and_ignores_fenced_examples(
    tmp_path: Path,
    eol: bytes,
) -> None:
    target = tmp_path / "notes.md"
    host = tmp_path / "CLAUDE.md"
    host.symlink_to(target)
    lux = b"@.punt-labs/lux/CLAUDE.md"
    lines = [
        b"notes",
        b"````markdown",
        b"    ````",
        b"~~~",
        b"```",
        lux,
        b"````",
        b"@.punt-labs/vox/CLAUDE.md",
        b"other prose",
        b"",
    ]
    original = eol.join(lines)
    target.write_bytes(original)
    target.chmod(0o640)
    editor = ClaudeImport(ActivationFile(host), lux)
    editor.apply(add=True)
    assert target.read_bytes() == eol.join([*lines[:7], lux, *lines[7:]])
    assert target.stat().st_mode & 0o777 == 0o640
    assert host.is_symlink()
    before = target.stat().st_mtime_ns
    editor.apply(add=True)
    assert target.stat().st_mtime_ns == before
    editor.apply(add=False)
    assert target.read_bytes() == original


def test_open_fence_fails_before_granting(checkout: Checkout) -> None:
    host = checkout.root / "CLAUDE.md"
    host.write_text("notes\n```\n")
    with pytest.raises(ValueError, match="unclosed code fence"):
        Enablement(checkout, "project").apply("enable")
    assert not (checkout.root / ".claude").exists()
    assert not checkout.state().enabled


def test_parallel_and_reversed_enable_order_produce_identical_imports(
    tmp_path: Path,
) -> None:
    old_guide = b"@.punt-labs/biff/CLAUDE.md"
    other = b"@.punt-labs/vox/CLAUDE.md"
    lux = b"@.punt-labs/lux/CLAUDE.md"
    results: list[bytes] = []
    for order in ((lux, other), (other, lux)):
        host = ActivationFile(tmp_path / "CLAUDE.md")
        host.write(b"notes\n" + old_guide + b"\n")
        with ThreadPoolExecutor(max_workers=2) as workers:
            a, b = [
                workers.submit(ClaudeImport(host, line).apply, add=True)
                for line in order
            ]
            a.result()
            b.result()
        results.append(host.path.read_bytes())
    assert results == [b"\n".join([b"notes", old_guide, lux, other, b""])] * 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_mcp_dormancy_and_shared_enablement_service(checkout: Checkout) -> None:
    async with Client(mcp) as client:
        args = {"repo": str(checkout.root)}
        status = await client.call_tool("status", args)
        assert "integration: off" in str(status.data)
        dormant = await client.call_tool("display_mode_get", args, raise_on_error=False)
        assert dormant.is_error
        assert "Run /lux enable" in str(dormant.content)
        on = await client.call_tool("enablement", {**args, "action": "enable"})
        assert "integration: enabled" in str(on.data)
        assert checkout.state().deciding_file == checkout.root / PERSONAL / "enabled"
        active = await client.call_tool("display_mode_get", args)
        assert active.data == "display:off"
        Enablement(checkout, "local").apply("disable")
        dormant_again = await client.call_tool(
            "display_mode_get", args, raise_on_error=False
        )
        assert dormant_again.is_error
        assert "Run /lux enable" in str(dormant_again.content)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_mcp_activation_targets_the_invoking_worktree(
    checkout: Checkout, tmp_path_factory: pytest.TempPathFactory
) -> None:
    linked = tmp_path_factory.mktemp("lux-mcp-worktree")
    git(checkout.root, "worktree", "add", "--detach", str(linked))
    nested = linked / "nested"
    nested.mkdir()
    args = {"repo": str(nested)}
    async with Client(mcp) as client:
        enabled = await client.call_tool("enablement", {**args, "action": "enable"})
        assert str(linked / PERSONAL / "enabled") in str(enabled.data)
        assert (linked / PERSONAL / "enabled").exists()
        assert not checkout.state().enabled
        status = await client.call_tool("status", args)
        assert "integration: enabled" in str(status.data)
        assert not (await client.call_tool("display_mode_get", args)).is_error
        await client.call_tool("enablement", {**args, "action": "disable"})
        assert not Checkout(linked).state().enabled
        assert not checkout.state().enabled


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_mcp_status_does_not_bind_a_checkout(checkout: Checkout) -> None:
    async with Client(mcp) as client:
        status = await client.call_tool("status", {"repo": str(checkout.root)})
        assert "integration: off" in str(status.data)
        joined = await client.call_tool(
            "session_identify", {"kind": "mcp-session", "name": "headless"}
        )
        assert joined.data == "identified:headless"
        assert not (await client.call_tool("scene_ls", {})).is_error
