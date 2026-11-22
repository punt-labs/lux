"""Report-only import contracts for the future packages in the platform plan.

No findings gate builds: this tool reports migration work, never enforces it.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import ClassVar, Self


class LayerContract:
    """Classify current modules against the planned package dependency graph."""

    _prefixes: ClassVar[dict[str, str]] = {
        "kernel": "tracing bounded_send send_timeout write_progress progress_clock "
        "polled_event connection_timing socket_owner client_host connection_identity "
        "paths log_level proctitle repo_root runtime logging_config usage "
        "credentials socket_writer wire_queue",
        "wire": "domain protocol operations.models",
        "trust": "trust",
        "service": "service _backend_* _backends _platform_dispatch _launchctl "
        "_legacy_sweep* _binary_sweep* _shim_ownership _atomic_write _port_guard "
        "_service_* _doctor_result doctor_* hub_restart display_restart hooks "
        "claude_permissions permission_rules display_enablement config "
        "_launchd_plist entry_runtime applet_event session_start",
        "client": "client hub_client rest_transport rest_http_call rest_loopback "
        "rest_reply rest_error_body identity_headers header_value cli_identity "
        "hub_paths",
        "hub": "domain.hub operations commands tools rest luxd mcp_transport "
        "mcp_endpoint mcp_session session_cleanup session_key ws_transport ws_listen "
        "transport_policy hub_composition hub_lifespan mcp_session_manager "
        "mcp_session_scope",
        "display": "display luxd_display",
        "terminal": "terminal",
        "pty": "ptyd",
        "cli": "cli __main__ hook_cli",
        "applets": "applets apps",
    }
    _allowed: ClassVar[dict[str, set[str]]] = {
        "kernel": set(),
        "wire": {"kernel"},
        "trust": {"kernel"},
        "service": {"kernel", "wire", "trust"},
        "client": {"kernel", "wire", "trust"},
        "hub": {"kernel", "wire", "trust", "service"},
        "display": {"kernel", "wire", "trust", "service", "terminal"},
        "terminal": {"kernel", "wire"},
        "pty": {"kernel", "wire", "trust", "service", "client", "terminal"},
        "cli": {"kernel", "wire", "trust", "service", "client", "applets"},
        "applets": {"kernel", "wire", "trust", "service", "client"},
    }

    def classify(self, module: str) -> str:
        if module == "punt_lux":
            return "root"
        if not module.startswith("punt_lux."):
            return "unassigned"
        relative = module.removeprefix("punt_lux.")
        matches = [
            (len(prefix.rstrip("*")), layer)
            for layer, prefixes in self._prefixes.items()
            for prefix in prefixes.split()
            if (
                relative.startswith(prefix[:-1])
                if prefix.endswith("*")
                else relative == prefix or relative.startswith(prefix + ".")
            )
        ]
        return max(matches)[1] if matches else "unassigned"

    def breaks_rule(self, source: str, target: str) -> bool:
        exempt = {"root", "unassigned"}
        return (
            source not in exempt
            and target not in exempt
            and source != target
            and target not in self._allowed.get(source, set())
        )


class RuntimeImports(ast.NodeVisitor):
    """Collect import names without traversing annotation-only branches."""

    _package: list[str]
    _names: set[str]
    _guards: set[str]
    _typing: set[str]

    def __new__(cls, module: str, *, is_package: bool = False) -> Self:
        self = super().__new__(cls)
        self._package = module.split(".") if is_package else module.split(".")[:-1]
        self._names = set()
        self._guards = {"TYPE_CHECKING"}
        self._typing = {"typing"}
        return self

    def collect(self, source: str) -> frozenset[str]:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "typing":
                self._guards.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "TYPE_CHECKING"
                )
            elif isinstance(node, ast.Import):
                self._typing.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "typing"
                )
        self.visit(tree)
        return frozenset(self._names)

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        guarded = (isinstance(test, ast.Name) and test.id in self._guards) or (
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and test.value.id in self._typing
        )
        if guarded:
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self._names.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = (
            self._package[: len(self._package) - node.level + 1] if node.level else []
        )
        origin = (
            ".".join([*base, *node.module.split(".")])
            if node.module
            else ".".join(base)
        )
        self._names.add(origin)
        self._names.update(f"{origin}.{alias.name}" for alias in node.names)


class LayerReport:
    """Read a source tree and render unique runtime module edges."""

    _src: Path
    _contract: LayerContract

    def __new__(cls, src: Path) -> Self:
        self = super().__new__(cls)
        self._src = src
        self._contract = LayerContract()
        return self

    def render(self) -> str:
        modules: dict[str, Path] = {}
        for path in sorted((self._src / "punt_lux").rglob("*.py")):
            parts = path.relative_to(self._src).with_suffix("").parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            modules[module] = path
        groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        edges: set[tuple[str, str]] = set()
        errors: list[str] = []
        for module, path in modules.items():
            try:
                imports = RuntimeImports(module, is_package=path.name == "__init__.py")
                names = imports.collect(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeError) as error:
                errors.append(f"  {module}: {error}")
                continue
            for target in sorted(names & modules.keys()):
                if target == module:
                    continue
                edges.add((module, target))
                layers = (
                    self._contract.classify(module),
                    self._contract.classify(target),
                )
                if self._contract.breaks_rule(*layers):
                    groups[layers].append((module, target))
        lines = ["Layer contract (REPORT ONLY; runtime imports; unique module edges)"]
        for (source, target), violations in sorted(
            groups.items(), key=lambda item: (-len(item[1]), item[0])
        ):
            lines.append(f"{source} → {target}: {len(violations)}")
            lines.extend(f"  {left} → {right}" for left, right in violations)
        unassigned = [m for m in modules if self._contract.classify(m) == "unassigned"]
        lines.append(f"Unassigned modules: {len(unassigned)} (not errors)")
        lines.extend(f"  {module}" for module in unassigned)
        lines.append(
            "Root entry: punt_lux (exempt)"
            if "punt_lux" in modules
            else "Root entry: absent"
        )
        lines.extend([f"Unreadable modules: {len(errors)}", *errors])
        violations_count = sum(map(len, groups.values()))
        lines.append(
            f"Totals: {len(modules)} modules, {len(edges)} runtime edges, "
            f"{violations_count} violations in {len(groups)} groups, "
            f"{len(unassigned)} unassigned, {len(errors)} read errors"
        )
        return "\n".join(lines)


if __name__ == "__main__":
    print(LayerReport(Path(__file__).resolve().parents[1] / "src").render())
