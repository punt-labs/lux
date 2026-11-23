"""Future-package contract classification and runtime-edge ratchet."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.layer_contract import (
    LayerContract,
    LayerRatchet,
    LayerReport,
    RuntimeImports,
)


class TestLayerContract:
    @pytest.mark.parametrize(
        ("module", "layer"),
        [
            ("punt_lux", "root"),
            ("punt_lux.wire.model.elements", "wire"),
            ("punt_lux.hub.scene", "hub"),
            ("punt_lux.operations.models.reply", "wire"),
            ("punt_lux.operations.scene", "hub"),
            ("punt_lux.service._backend_systemd", "service"),
            ("punt_lux.service._legacy_sweep_disk", "service"),
            ("punt_lux.kernel.hub_paths", "kernel"),
            ("punt_lux.kernel.connection_id", "kernel"),
            ("punt_lux.kernel.programmer_error", "kernel"),
            ("punt_lux.wire", "wire"),
            ("punt_lux.wire.model.lease_term", "wire"),
            ("punt_lux.service.display_paths", "service"),
            ("punt_lux.cli.display_enablement", "cli"),
            ("punt_lux.service.display_mode_store", "service"),
            ("punt_lux.service.doctor_checks", "service"),
            ("punt_lux.client_host", "kernel"),
            ("punt_lux.credentials", "kernel"),
            ("punt_lux.socket_writer", "kernel"),
            ("punt_lux.wire_queue", "kernel"),
            ("punt_lux.client.connection", "client"),
            ("punt_lux.client.hub_client", "client"),
            ("punt_lux.client.rest_transport", "client"),
            ("punt_lux.client._rest_transport", "client"),
            ("punt_lux.wire.model.client_identity", "wire"),
            ("punt_lux.wire.model.applet_name_format", "wire"),
            ("punt_lux.luxd_display", "display"),
            ("punt_lux.__main__", "cli"),
            ("punt_lux.applets.beads.board", "applets"),
            ("punt_lux.trust.identity", "trust"),
            ("punt_lux.pty", "pty"),
            ("punt_lux.pty.service", "pty"),
            ("punt_lux.terminal", "terminal"),
            ("punt_lux.terminal.connection", "terminal"),
            ("punt_lux.terminal.snapshot", "terminal"),
            ("punt_lux.terminal.snapshot_encoding", "terminal"),
            ("punt_lux.terminal.output", "terminal"),
            ("punt_lux.wire.stream.frames", "wire"),
            ("punt_lux.display.terminal.remote_pool", "display"),
            ("punt_lux.service._launchd_plist", "service"),
            ("punt_lux.service.entry_runtime", "service"),
            ("punt_lux.hub_lifespan", "hub"),
            ("punt_lux.mcp_session_manager", "hub"),
            ("punt_lux.mcp_session_scope", "hub"),
            ("punt_lux.logging_config", "kernel"),
            ("punt_lux.usage", "kernel"),
            ("punt_lux.service.applet_event", "service"),
            ("punt_lux.hook_cli", "cli"),
            ("punt_lux.service.session_start", "service"),
            ("punt_lux.terminalish", "unassigned"),
            ("punt_lux.ptyish", "unassigned"),
            ("punt_lux.clientish", "unassigned"),
            ("punt_lux.hub_client", "unassigned"),
            ("punt_lux.rest_transport", "unassigned"),
            ("other.domain", "unassigned"),
            ("", "unassigned"),
        ],
    )
    def test_classifies_longest_module_prefix(self, module: str, layer: str) -> None:
        assert LayerContract().classify(module) == layer

    @pytest.mark.parametrize(
        ("source", "target", "violation"),
        [
            ("kernel", "wire", True),
            ("wire", "kernel", False),
            ("hub", "client", True),
            ("hub", "service", False),
            ("cli", "applets", False),
            ("applets", "cli", True),
            ("client", "client", False),
            ("root", "hub", False),
            ("hub", "root", False),
            ("unassigned", "hub", False),
            ("hub", "unassigned", False),
            ("display", "terminal", False),
            ("display", "pty", True),
            ("terminal", "pty", True),
            ("terminal", "kernel", False),
            ("terminal", "wire", False),
            ("terminal", "trust", True),
            ("terminal", "service", True),
            ("terminal", "client", True),
            ("terminal", "hub", True),
            ("terminal", "display", True),
            ("terminal", "terminal", False),
            ("pty", "pty", False),
            ("pty", "kernel", False),
            ("pty", "wire", False),
            ("pty", "trust", False),
            ("pty", "service", False),
            ("pty", "client", False),
            ("pty", "terminal", False),
            ("pty", "display", True),
            ("pty", "hub", True),
        ],
    )
    def test_reports_only_disallowed_known_layers(
        self, source: str, target: str, violation: bool
    ) -> None:
        assert LayerContract().breaks_rule(source, target) is violation

    @pytest.mark.parametrize("source", ["hub", "cli", "applets", "client", "service"])
    @pytest.mark.parametrize("target", ["terminal", "pty"])
    def test_existing_layers_cannot_import_terminal_or_pty(
        self, source: str, target: str
    ) -> None:
        assert LayerContract().breaks_rule(source, target)


class TestRuntimeImports:
    @pytest.mark.parametrize(
        "guard",
        ["TYPE_CHECKING", "typing.TYPE_CHECKING", "tc", "t.TYPE_CHECKING"],
    )
    def test_excludes_type_guards_but_keeps_runtime_else(self, guard: str) -> None:
        names = RuntimeImports("punt_lux.wire.model").collect(
            "from typing import TYPE_CHECKING as tc\nimport typing as t\n"
            f"if {guard}:\n    import punt_lux.cli\n"
            "else:\n    from .. import tracing\n"
            "def deferred():\n    import punt_lux.client\n"
        )
        assert "punt_lux.cli" not in names
        assert {"punt_lux.tracing", "punt_lux.client"} <= names

    def test_resolves_package_relative_imports(self) -> None:
        names = RuntimeImports("punt_lux.wire", is_package=True).collect(
            "from . import model\nfrom ..tracing import trace\n"
        )
        assert "punt_lux.wire.model" in names
        assert "punt_lux.tracing" in names

    def test_empty_source(self) -> None:
        assert RuntimeImports("punt_lux").collect("") == frozenset()

    def test_invalid_source_is_explicit(self) -> None:
        with pytest.raises(SyntaxError):
            RuntimeImports("punt_lux").collect("from ???")


class TestLayerReport:
    def test_reports_daemon_boundaries_but_allows_headless_terminal(
        self, tmp_path: Path
    ) -> None:
        package = tmp_path / "punt_lux"
        package.mkdir()
        (package / "display.py").write_text(
            "import punt_lux.terminal\nimport punt_lux.pty\n"
        )
        (package / "terminal.py").write_text("import punt_lux.pty\n")
        (package / "pty.py").write_text("import punt_lux.terminal\n")
        (package / "cli.py").write_text("import punt_lux.pty\n")
        report = LayerReport(tmp_path).render()
        assert "display → pty: 1" in report
        assert "terminal → pty: 1" in report
        assert "cli → pty: 1" in report
        assert "display → terminal:" not in report
        assert "pty → terminal:" not in report
        assert "3 violations in 3 groups, 0 unassigned, 0 read errors" in report

    def test_groups_unique_edges_and_reports_unassigned(self, tmp_path: Path) -> None:
        package = tmp_path / "punt_lux"
        package.mkdir()
        (package / "__init__.py").write_text("import punt_lux.cli\n")
        (package / "tracing.py").write_text(
            "import punt_lux.cli\nimport punt_lux.cli\n"
            "from punt_lux.cli import function\n"
            "if TYPE_CHECKING:\n    import punt_lux.unknown\n"
        )
        (package / "cli.py").write_text("import punt_lux.tracing\n")
        (package / "unknown.py").write_text("import missing_dependency\n")
        report = LayerReport(tmp_path).render()
        assert "kernel → cli: 1" in report
        assert "punt_lux.tracing → punt_lux.cli" in report
        assert "Unassigned modules: 1 (not errors)\n  punt_lux.unknown" in report
        assert "Root entry: punt_lux (exempt)" in report
        assert "Totals: 4 modules, 3 runtime edges, 1 violations in 1 groups" in report

    def test_missing_tree_is_empty_report(self, tmp_path: Path) -> None:
        assert (
            "Totals: 0 modules, 0 runtime edges, 0 violations"
            in LayerReport(tmp_path).render()
        )

    def test_syntax_errors_are_reported_not_raised(self, tmp_path: Path) -> None:
        package = tmp_path / "punt_lux"
        package.mkdir()
        (package / "broken.py").write_text("import ???")
        report = LayerReport(tmp_path).render()
        assert "Unreadable modules: 1" in report
        assert "1 unassigned, 1 read errors" in report


class TestLayerRatchet:
    @pytest.fixture
    def source(self, tmp_path: Path) -> Path:
        package = tmp_path / "src" / "punt_lux"
        package.mkdir(parents=True)
        (package / "tracing.py").write_text("import punt_lux.cli\n")
        (package / "cli.py").write_text("")
        return package.parent

    def test_new_violation_fails(
        self, source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text("[]\n")
        assert LayerRatchet(source, baseline).run() == 1
        output = capsys.readouterr().out
        assert "New layer violations: 1" in output
        assert "punt_lux.tracing → punt_lux.cli" in output

    def test_baseline_violation_passes(
        self, source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(["punt_lux.tracing → punt_lux.cli"]))
        assert LayerRatchet(source, baseline).run() == 0
        assert "Layer ratchet passed: 1 known violations" in capsys.readouterr().out

    def test_stale_entry_fails_and_update_shrinks(
        self, source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(["punt_lux.tracing → punt_lux.cli"]))
        (source / "punt_lux" / "tracing.py").write_text("")
        ratchet = LayerRatchet(source, baseline)
        assert ratchet.run() == 1
        output = capsys.readouterr().out
        assert "Stale layer baseline entries (removable): 1" in output
        assert "punt_lux.tracing → punt_lux.cli" in output
        assert "make update-layers" in output
        assert ratchet.run(update=True) == 0
        assert json.loads(baseline.read_text()) == []
        assert ratchet.run() == 0

    def test_update_cannot_accept_new_violations(
        self, source: Path, tmp_path: Path
    ) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text("[]\n")
        assert LayerRatchet(source, baseline).run(update=True) == 1
        assert baseline.read_text() == "[]\n"

    def test_missing_baseline_requires_explicit_bootstrap(
        self, source: Path, tmp_path: Path
    ) -> None:
        baseline = tmp_path / "baseline.json"
        ratchet = LayerRatchet(source, baseline)
        assert ratchet.run() == 1
        assert ratchet.run(update=True) == 0
        assert json.loads(baseline.read_text()) == ["punt_lux.tracing → punt_lux.cli"]
        assert ratchet.run() == 0

    @pytest.mark.parametrize("raw", ["{", "{}", "[1]", "null"])
    def test_invalid_baseline_fails(
        self, source: Path, tmp_path: Path, raw: str
    ) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text(raw)
        assert LayerRatchet(source, baseline).run() == 1
        assert LayerRatchet(source, baseline).run(update=True) == 1
        assert baseline.read_text() == raw

    def test_unreadable_source_prevents_check_and_update(
        self, source: Path, tmp_path: Path
    ) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text("[]\n")
        (source / "punt_lux" / "tracing.py").write_text("import ???")
        ratchet = LayerRatchet(source, baseline)
        assert ratchet.run() == 1
        assert ratchet.run(update=True) == 1
        assert baseline.read_text() == "[]\n"

    def test_empty_tree_and_baseline_pass(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text("[]\n")
        assert LayerRatchet(tmp_path, baseline).run() == 0

    def test_unreadable_baseline_fails(self, source: Path, tmp_path: Path) -> None:
        assert LayerRatchet(source, tmp_path).run() == 1

    @pytest.mark.parametrize(
        "mode", ["grew", "shrank", "unchanged", "absent", "invalid", "deleted"]
    )
    @pytest.mark.parametrize("explicit", [True, False])
    def test_compares_baseline_with_git_base(
        self,
        source: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        mode: str,
        explicit: bool,
    ) -> None:
        edge = "punt_lux.tracing → punt_lux.cli"
        baseline = tmp_path / "baseline.json"
        git = shutil.which("git")
        assert git is not None
        subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
        if mode != "absent":
            baseline.write_text(
                "{"
                if mode == "invalid"
                else json.dumps([] if mode in {"grew", "deleted"} else [edge])
            )
            subprocess.run([git, "add", baseline.name], cwd=tmp_path, check=True)
        subprocess.run(
            [
                git,
                "-c",
                "user.name=Layer Test",
                "-c",
                "user.email=layer@example.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "base",
                "--allow-empty",
            ],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            [git, "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=tmp_path,
            check=True,
        )
        baseline.write_text(json.dumps([] if mode == "shrank" else [edge]))
        if mode == "shrank":
            (source / "punt_lux" / "tracing.py").write_text("")
        if mode == "deleted":
            baseline.unlink()
        result = LayerRatchet(source, baseline).run(
            base_ref="HEAD" if explicit else "", update=mode == "deleted"
        )
        assert result == (1 if mode in {"grew", "invalid", "deleted"} else 0)
        output = capsys.readouterr().out
        if mode in {"grew", "deleted"}:
            assert "layer baseline grew vs" in output
            assert edge in output
        if mode == "deleted":
            assert not baseline.exists()
        if mode == "absent":
            assert "skipping baseline growth check" in output

    def test_invalid_explicit_git_ref_fails(
        self, source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(["punt_lux.tracing → punt_lux.cli"]))
        assert LayerRatchet(source, baseline).run(base_ref="missing-ref") == 1
        assert "Layer ratchet FAILED" in capsys.readouterr().out
