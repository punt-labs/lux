"""Future-package contract classification and runtime-only reporting."""

from pathlib import Path

import pytest

from tools.layer_contract import LayerContract, LayerReport, RuntimeImports


class TestLayerContract:
    @pytest.mark.parametrize(
        ("module", "layer"),
        [
            ("punt_lux", "root"),
            ("punt_lux.domain.elements", "wire"),
            ("punt_lux.domain.hub.scene", "hub"),
            ("punt_lux.operations.models.reply", "wire"),
            ("punt_lux.operations.scene", "hub"),
            ("punt_lux._backend_systemd", "service"),
            ("punt_lux._legacy_sweep_disk", "service"),
            ("punt_lux.doctor_checks", "service"),
            ("punt_lux.client_host", "kernel"),
            ("punt_lux.client.connection", "client"),
            ("punt_lux.luxd_display", "display"),
            ("punt_lux.__main__", "cli"),
            ("punt_lux.apps.clock", "applets"),
            ("punt_lux.trust.identity", "trust"),
            ("punt_lux.clientish", "unassigned"),
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
        ],
    )
    def test_reports_only_disallowed_known_layers(
        self, source: str, target: str, violation: bool
    ) -> None:
        assert LayerContract().breaks_rule(source, target) is violation


class TestRuntimeImports:
    @pytest.mark.parametrize(
        "guard",
        ["TYPE_CHECKING", "typing.TYPE_CHECKING", "tc", "t.TYPE_CHECKING"],
    )
    def test_excludes_type_guards_but_keeps_runtime_else(self, guard: str) -> None:
        names = RuntimeImports("punt_lux.domain.model").collect(
            "from typing import TYPE_CHECKING as tc\nimport typing as t\n"
            f"if {guard}:\n    import punt_lux.cli\n"
            "else:\n    from .. import tracing\n"
            "def deferred():\n    import punt_lux.client\n"
        )
        assert "punt_lux.cli" not in names
        assert {"punt_lux.tracing", "punt_lux.client"} <= names

    def test_resolves_package_relative_imports(self) -> None:
        names = RuntimeImports("punt_lux.domain", is_package=True).collect(
            "from . import hub\nfrom ..tracing import trace\n"
        )
        assert "punt_lux.domain.hub" in names
        assert "punt_lux.tracing" in names

    def test_empty_source(self) -> None:
        assert RuntimeImports("punt_lux").collect("") == frozenset()

    def test_invalid_source_is_explicit(self) -> None:
        with pytest.raises(SyntaxError):
            RuntimeImports("punt_lux").collect("from ???")


class TestLayerReport:
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
