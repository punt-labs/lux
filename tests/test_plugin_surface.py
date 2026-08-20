"""Behavioral tests for scripts/check-plugin-surface.sh.

A marketplace install fetches only the ``plugin/`` directory, so a path that
resolves outside it, or to a file the surface does not ship, is invisible in the
source tree and broken on every installed copy. The gate exists to catch that
class; these tests drive it as a subprocess against fixture surfaces and assert
it actually rejects each shape, because a guard that never fires is
indistinguishable from no guard at all.

The symlink case is the one that justifies resolving paths rather than scanning
for ``../``: the link's text is clean and its target exists here, so both a
textual scan and an existence check pass it, while the install gets a dangling
link.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-plugin-surface.sh"


def _run(surface: Path | None = None) -> subprocess.CompletedProcess[str]:
    argv = ["bash", str(_SCRIPT)]
    if surface is not None:
        argv.append(str(surface))
    return subprocess.run(argv, text=True, capture_output=True, check=False)


def _make_executable(path: Path) -> None:
    """Add the exec bits git would carry, without widening anything else."""
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_hooks_json(hooks_dir: Path, command: str) -> None:
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": command}]}
                    ]
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _make_surface(root: Path, *, hook: str = "session-start.sh") -> Path:
    """Build a minimal well-formed surface: a manifest, a command, one hook."""
    surface = root / "plugin"
    (surface / ".claude-plugin").mkdir(parents=True)
    (surface / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "fixture"}), encoding="utf-8"
    )
    (surface / "commands").mkdir()
    (surface / "commands" / "thing.md").write_text("do a thing\n", encoding="utf-8")
    hooks = surface / "hooks"
    hooks.mkdir()
    _write_hooks_json(hooks, f"${{CLAUDE_PLUGIN_ROOT}}/hooks/{hook}")
    script = hooks / hook
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _make_executable(script)
    return surface


class TestAcceptsAWellFormedSurface:
    def test_clean_surface_passes(self, tmp_path: Path) -> None:
        result = _run(_make_surface(tmp_path))
        assert result.returncode == 0, result.stderr
        assert "all resolve inside plugin/" in result.stdout

    def test_the_real_surface_passes(self) -> None:
        # No argument: the gate defaults to this repo's own plugin/ directory.
        result = _run()
        assert result.returncode == 0, result.stderr

    def test_unquoted_glob_reference_passes(self, tmp_path: Path) -> None:
        # A glob's matches cannot be verified statically, so the gate checks the
        # directory prefix and stops. Capturing the `*` as part of the path
        # instead would reject correct code with "does not ship".
        surface = _make_surface(tmp_path)
        (surface / "hooks" / "loop.sh").write_text(
            "#!/usr/bin/env bash\n"
            "for f in ${CLAUDE_PLUGIN_ROOT}/hooks/*.sh; do\n"
            "  :\n"
            "done\n",
            encoding="utf-8",
        )
        result = _run(surface)
        assert result.returncode == 0, result.stderr

    def test_self_root_derivation_passes(self, tmp_path: Path) -> None:
        # `dirname "$0"/..` is how a hook correctly finds its own plugin root.
        # It walks up one level and lands exactly on the surface, so a blanket
        # ban on upward path segments would reject the correct idiom.
        surface = _make_surface(tmp_path)
        (surface / "hooks" / "session-start.sh").write_text(
            "#!/usr/bin/env bash\n"
            'PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'cat "${PLUGIN_ROOT}/.claude-plugin/plugin.json"\n',
            encoding="utf-8",
        )
        _make_executable(surface / "hooks" / "session-start.sh")
        result = _run(surface)
        assert result.returncode == 0, result.stderr


class TestRejectsAReferenceTheSurfaceCannotSatisfy:
    def test_missing_target_fails(self, tmp_path: Path) -> None:
        surface = _make_surface(tmp_path)
        (surface / "hooks" / "session-start.sh").unlink()
        result = _run(surface)
        assert result.returncode == 1
        assert "does not ship" in result.stderr

    def test_reference_escaping_the_surface_fails(self, tmp_path: Path) -> None:
        # The prfaq failure shape: a runtime step reaching into a sibling
        # directory that cone mode leaves out of the install.
        surface = _make_surface(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "helper.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        _write_hooks_json(surface / "hooks", "${CLAUDE_PLUGIN_ROOT}/../src/helper.sh")
        result = _run(surface)
        assert result.returncode == 1
        assert "escapes the plugin surface" in result.stderr

    def test_deep_relative_escape_fails(self, tmp_path: Path) -> None:
        surface = _make_surface(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "punt_lux.py").write_text("x = 1\n", encoding="utf-8")
        _write_hooks_json(
            surface / "hooks", "${CLAUDE_PLUGIN_ROOT}/hooks/../../src/punt_lux.py"
        )
        result = _run(surface)
        assert result.returncode == 1
        assert "escapes the plugin surface" in result.stderr

    def test_non_executable_hook_fails(self, tmp_path: Path) -> None:
        surface = _make_surface(tmp_path)
        script = surface / "hooks" / "session-start.sh"
        script.chmod(script.stat().st_mode & ~0o111)
        result = _run(surface)
        assert result.returncode == 1
        assert "not executable" in result.stderr

    def test_non_executable_extensionless_hook_fails(self, tmp_path: Path) -> None:
        # The exec bit matters because Claude Code execs the command, and it
        # execs whatever hooks.json names — so keying the check off a `.sh`
        # suffix would let mode 0644 ship on a hook that simply has no suffix.
        # Classification, not spelling, decides what is a script.
        surface = _make_surface(tmp_path, hook="dispatch")
        script = surface / "hooks" / "dispatch"
        script.chmod(script.stat().st_mode & ~0o111)
        result = _run(surface)
        assert result.returncode == 1
        assert "not executable" in result.stderr


class TestRejectsWhatATextualScanWouldMiss:
    def test_symlink_out_of_the_surface_fails(self, tmp_path: Path) -> None:
        # The hole an `exists()`-only or `../`-scanning gate leaves open: the
        # reference text is clean, the target exists in the source tree, and the
        # install still gets a dangling link.
        surface = _make_surface(tmp_path)
        outside = tmp_path / "src"
        outside.mkdir()
        (outside / "helper.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (surface / "hooks" / "helper.sh").symlink_to(outside / "helper.sh")
        result = _run(surface)
        assert result.returncode == 1
        assert "symlink escapes the plugin surface" in result.stderr

    def test_sourced_file_outside_the_surface_fails(self, tmp_path: Path) -> None:
        surface = _make_surface(tmp_path)
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "common.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (surface / "hooks" / "session-start.sh").write_text(
            '#!/usr/bin/env bash\nsource "../../lib/common.sh"\n', encoding="utf-8"
        )
        _make_executable(surface / "hooks" / "session-start.sh")
        result = _run(surface)
        assert result.returncode == 1
        assert "sourced file escapes the plugin surface" in result.stderr

    def test_repo_root_variable_fails(self, tmp_path: Path) -> None:
        # `source "$REPO_ROOT/..."`: the path is assembled at runtime, so no
        # static resolution can see where it lands. Naming the repo root at all
        # is the defect.
        surface = _make_surface(tmp_path)
        (surface / "hooks" / "session-start.sh").write_text(
            '#!/usr/bin/env bash\nsource "$REPO_ROOT/scripts/lib.sh"\n',
            encoding="utf-8",
        )
        _make_executable(surface / "hooks" / "session-start.sh")
        result = _run(surface)
        assert result.returncode == 1
        assert "names the repository root" in result.stderr


class TestScansEveryFileTheSurfaceShips:
    """A suffix allowlist decides which files are *read*, so anything it omits
    is not merely unchecked — it is a place an escaping reference can be
    written and the gate will still report the surface clean."""

    def test_reference_inside_an_extensionless_script_fails(
        self, tmp_path: Path
    ) -> None:
        # A hook does not need a `.sh` name to be a hook: hooks.json names the
        # command, and Claude Code execs whatever it points at.
        surface = _make_surface(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "helper.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        dispatch = surface / "hooks" / "dispatch"
        dispatch.write_text(
            '#!/usr/bin/env bash\nexec "${CLAUDE_PLUGIN_ROOT}/../src/helper.sh"\n',
            encoding="utf-8",
        )
        _make_executable(dispatch)
        result = _run(surface)
        assert result.returncode == 1
        assert "escapes the plugin surface" in result.stderr

    def test_sourced_file_in_an_extensionless_script_fails(
        self, tmp_path: Path
    ) -> None:
        # The shebang, not the suffix, is what makes a file a shell script.
        surface = _make_surface(tmp_path)
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "common.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        dispatch = surface / "hooks" / "dispatch"
        dispatch.write_text(
            '#!/usr/bin/env bash\nsource "../../lib/common.sh"\n', encoding="utf-8"
        )
        _make_executable(dispatch)
        result = _run(surface)
        assert result.returncode == 1
        assert "sourced file escapes the plugin surface" in result.stderr

    def test_binary_file_does_not_break_the_gate(self, tmp_path: Path) -> None:
        # Reading every file means meeting the ones that are not text. A PNG in
        # skills/ must neither crash the gate nor produce a finding.
        surface = _make_surface(tmp_path)
        (surface / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00")
        result = _run(surface)
        assert result.returncode == 0, result.stderr


class TestFailsClosed:
    def test_absent_surface_is_an_error(self, tmp_path: Path) -> None:
        result = _run(tmp_path / "nope")
        assert result.returncode == 2
        assert "plugin surface not found" in result.stderr

    def test_unmatched_hooks_json_is_an_error(self, tmp_path: Path) -> None:
        # If hooks.json stops carrying the placeholder, the extraction pattern
        # has rotted and every later check would pass vacuously. That is the
        # exact shape of the trailing-slash bug in restore-dev-plugin.sh: a
        # guard whose condition could never be true.
        surface = _make_surface(tmp_path)
        _write_hooks_json(surface / "hooks", "/absolute/path/session-start.sh")
        result = _run(surface)
        assert result.returncode == 2
        assert "extraction pattern no longer matches" in result.stderr
