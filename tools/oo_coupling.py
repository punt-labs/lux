"""Module coupling and class cohesion metrics for Python packages.

Measures how tightly modules are connected (coupling) and how well each
class's methods work with common instance state (LCOM cohesion). Produces
JSON output with numeric scores for agent consumption.

Usage:
    python oo_coupling.py <file_or_directory> [--json] [--threshold]
    python oo_coupling.py <file_or_directory> --check         # ratchet check
    python oo_coupling.py <file_or_directory> --update        # update baseline
    python oo_coupling.py <file_or_directory> --rebaseline    # unconditional reset
    python oo_coupling.py <file_or_directory> --rebaseline-files <path>[,<path>...] \
        --reason "<why this bless is necessary>"
        # DES-096: bounded, scoped, tool-computed bless. Recomputes and
        # records the baseline for ONLY the named files (repo-relative paths
        # as they appear as keys in .oo-coupling-baseline.json), leaving
        # every other file's baseline untouched -- unlike --rebaseline,
        # which resets the whole tree. --reason is REQUIRED: it is recorded
        # in the audit log alongside every blessed file, because the tool
        # cannot judge "genuinely necessary first edge" -- the human-
        # supplied reason is the accountability. Refuses each named file --
        # per-file, not all-or-nothing -- whose recomputed metric strictly
        # EXCEEDS that metric's absolute PL-CU-1 threshold AND REGRESSED
        # against the file's existing baseline value for that metric (a
        # value exactly AT the cap is within-threshold and is recorded; an
        # over-cap value that is unchanged or improved vs. baseline is
        # carried forward, not refused -- it is already grandfathered by
        # check()/update()'s own no-regression rule), or that was not
        # scored (not in the tree); every other named file is still
        # blessed. A file with no existing baseline entry has nothing to
        # grandfather against, so any over-cap metric on it refuses
        # unconditionally. This permits recording a within-cap coupling
        # regression -- the first-edge-under-cap case --update's strict
        # no-regression rule would otherwise refuse -- on a file that
        # separately carries an unrelated, unchanged, pre-existing
        # over-cap metric.
    python oo_coupling.py <file_or_directory> --log           # audit history
    python oo_coupling.py <file_or_directory> --check --base-ref <ref>
        # scope --check's touched-file diff to <ref>..HEAD. Omitted, --check
        # resolves merge-base(origin/main, HEAD) itself -- the same default
        # oo_score.py's GitRepo.resolve_base already computes -- so a bare
        # local run scores the whole fork-to-HEAD range, not just the last
        # commit. CI still passes an explicit <ref> on both triggers, as
        # belt-and-suspenders against this default's own fallback (HEAD~1,
        # used when merge-base cannot resolve): the push-to-main
        # job passes the pre-push tip of main (github.event.before) so a
        # multi-commit push is scored as a whole range; the pull_request job
        # passes its own computed merge-base(origin/main, HEAD) for the
        # identical reason on a multi-commit PR

Metrics produced:
    efferent_coupling    count of internal package modules imported (target: <= 7)
    public_names         names in __all__ or public module-level names (target: <= 15)
    circular_imports     1 if in a cycle, 0 otherwise (target: == 0)
    max_lcom             highest LCOM across classes in a module (target: <= 0.8)
    avg_lcom             average LCOM across classes in a module (target: <= 0.5)
"""

from __future__ import annotations

import ast
import datetime
import json
import os
import subprocess
import sys
from itertools import combinations
from pathlib import Path
from typing import ClassVar, Self


def _writeln(text: str = "") -> None:
    """Write a line to stdout."""
    sys.stdout.write(text + "\n")


# ------------------------------------------------------------------
# Metric collection
# ------------------------------------------------------------------


class ModuleCouplingMetrics:
    """Compute coupling and cohesion metrics for a single Python module."""

    _path: str
    _tree: ast.Module
    _package_modules: frozenset[str]
    _package_name: str

    def __new__(
        cls,
        path: str,
        source: str,
        package_modules: frozenset[str],
        package_name: str = "",
    ) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._tree = ast.parse(source, filename=path)
        self._package_modules = package_modules
        self._package_name = package_name
        return self

    def compute(self) -> dict[str, float | int | str]:
        """Return all metrics for this module."""
        lcom_values = self._class_lcom_values()
        return {
            "file": self._path,
            "efferent_coupling": self._efferent_coupling(),
            "public_names": self._public_names(),
            "circular_imports": 0,  # set by CouplingScorer after graph analysis
            "max_lcom": max(lcom_values) if lcom_values else 0.0,
            "avg_lcom": (
                round(sum(lcom_values) / len(lcom_values), 3) if lcom_values else 0.0
            ),
        }

    # ---- efferent coupling ----

    def _efferent_coupling(self) -> int:
        """Count distinct internal package modules imported."""
        own_key = Path(self._path).stem
        imported = CouplingScorer._parse_internal_imports(
            self._tree,
            own_key,
            self._package_modules,
            self._package_name,
        )
        return len(imported)

    # ---- public names ----

    def _public_names(self) -> int:
        """Count public names: prefer __all__ if present, else heuristic."""
        for node in ast.iter_child_nodes(self._tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "__all__"
                        and isinstance(node.value, (ast.List, ast.Tuple))
                    ):
                        return len(node.value.elts)
        # No __all__ — count public module-level names
        count = 0
        for node in ast.iter_child_nodes(self._tree):
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                count += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    count += 1
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_"):
                        count += 1
        return count

    # ---- LCOM ----

    @staticmethod
    def _is_type_definition(node: ast.ClassDef) -> bool:
        """Return True for Protocol and TypedDict classes (skip for LCOM)."""
        type_bases = {"Protocol", "TypedDict"}
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in type_bases:
                return True
            if (
                isinstance(base, ast.Subscript)
                and isinstance(base.value, ast.Name)
                and base.value.id in type_bases
            ):
                return True
        return False

    @staticmethod
    def _method_self_attrs(method: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        """Return set of self._* attribute names accessed in a method."""
        attrs: set[str] = set()
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr.startswith("_")
            ):
                attrs.add(node.attr)
        return attrs

    def _class_lcom(self, cls_node: ast.ClassDef) -> float | None:
        """Compute LCOM for a single class. Return None if < 2 methods."""
        methods: list[set[str]] = []
        for item in ast.iter_child_nodes(cls_node):
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Skip static methods and class methods — they don't use self
            is_static = any(
                (isinstance(d, ast.Name) and d.id == "staticmethod")
                or (isinstance(d, ast.Attribute) and d.attr == "staticmethod")
                for d in item.decorator_list
            )
            is_classmethod = any(
                (isinstance(d, ast.Name) and d.id == "classmethod")
                or (isinstance(d, ast.Attribute) and d.attr == "classmethod")
                for d in item.decorator_list
            )
            if is_static or is_classmethod:
                continue
            methods.append(self._method_self_attrs(item))

        if len(methods) <= 1:
            return None  # 0-1 methods: LCOM undefined, treated as 0.0

        total_pairs = 0
        disjoint_pairs = 0
        for m1, m2 in combinations(methods, 2):
            total_pairs += 1
            if not m1 & m2:
                disjoint_pairs += 1

        if total_pairs == 0:
            return 0.0
        return round(disjoint_pairs / total_pairs, 3)

    def _class_lcom_values(self) -> list[float]:
        """Return LCOM values for all non-type-definition classes."""
        values: list[float] = []
        for node in ast.iter_child_nodes(self._tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if self._is_type_definition(node):
                continue
            lcom = self._class_lcom(node)
            if lcom is not None:
                values.append(lcom)
        return values


# ------------------------------------------------------------------
# Scoring and thresholds
# ------------------------------------------------------------------


class CouplingScorer:
    """Score modules against coupling/cohesion thresholds."""

    _thresholds: dict[str, tuple[str, float]]
    _results: list[dict[str, float | int | str]]

    THRESHOLDS: ClassVar[dict[str, tuple[str, float]]] = {
        "efferent_coupling": ("<=", 7),
        "public_names": ("<=", 15),
        "circular_imports": ("==", 0),
        "max_lcom": ("<=", 0.8),
        "avg_lcom": ("<=", 0.5),
    }

    MAIN_THRESHOLDS: ClassVar[dict[str, tuple[str, float]]] = {
        "public_names": ("<=", 100),
        "efferent_coupling": ("<=", 15),
    }

    def __new__(cls, target: Path) -> Self:
        self = super().__new__(cls)
        self._thresholds = cls.THRESHOLDS
        if target.is_file():
            pkg_dir = target.parent
            pkg_modules = self._discover_package_modules(pkg_dir)
            pkg_name = pkg_dir.name
            self._results = [self._score_file(target, pkg_modules, pkg_name)]
        elif target.is_dir():
            self._results = self._score_directory(target)
        else:
            self._results = []
        return self

    @property
    def results(self) -> list[dict[str, float | int | str]]:
        return self._results

    @property
    def summary(self) -> dict[str, float]:
        return self._aggregate()

    @property
    def grades(self) -> dict[str, str]:
        return {
            k: "PASS" if self._check(k, v) else "FAIL" for k, v in self.summary.items()
        }

    @property
    def fail_count(self) -> int:
        return sum(1 for g in self.grades.values() if g == "FAIL")

    def _check(self, metric: str, value: float | int, filepath: str = "") -> bool:
        thresholds = self._thresholds
        if filepath.endswith("__main__.py") and metric in self.MAIN_THRESHOLDS:
            thresholds = {**self._thresholds, **self.MAIN_THRESHOLDS}
        if metric not in thresholds:
            return True
        op, target = thresholds[metric]
        if op == ">=":
            return value >= target
        if op == "<=":
            return value <= target
        if op == "==":
            return value == target
        return True

    # ---- package discovery ----

    @staticmethod
    def _discover_package_modules(directory: Path) -> frozenset[str]:
        """Return module names at all levels, using dotted paths.

        Uses the same key format as _module_key: top-level stems,
        sub-package names, and dotted paths for nested modules.
        """
        names: set[str] = set()
        for py_file in sorted(directory.rglob("*.py")):
            if py_file.name.startswith("."):
                continue
            rel = py_file.relative_to(directory)
            parts = rel.with_suffix("").parts
            if len(parts) == 1:
                names.add(parts[0])
            elif parts[-1] == "__init__":
                names.add(".".join(parts[:-1]))
            else:
                names.add(".".join(parts))
        return frozenset(names)

    @staticmethod
    def _module_key(py_file: Path, pkg_dir: Path) -> str:
        """Return a stable key for a module relative to the package root.

        Top-level: stem (e.g., 'core').
        Sub-package __init__: directory name (e.g., 'voxd').
        Sub-package child: 'pkg.module' (e.g., 'voxd.config').
        """
        rel = py_file.relative_to(pkg_dir)
        parts = rel.with_suffix("").parts
        if len(parts) == 1:
            return parts[0]
        if parts[-1] == "__init__":
            return ".".join(parts[:-1])
        return ".".join(parts)

    # ---- shared import parser ----

    @staticmethod
    def _parse_internal_imports(
        tree: ast.Module,
        own_key: str,
        pkg_modules: frozenset[str],
        pkg_name: str,
    ) -> set[str]:
        """Return set of internal module names imported by this module."""
        imported: set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    top = parts[0]
                    if top in pkg_modules and top != own_key:
                        imported.add(top)
                    elif top == pkg_name and len(parts) > 1:
                        # Try progressively longer paths
                        inner_parts = parts[1:]
                        for i in range(len(inner_parts), 0, -1):
                            candidate = ".".join(inner_parts[:i])
                            if candidate in pkg_modules and candidate != own_key:
                                imported.add(candidate)
                                break
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None and node.level == 0:
                    parts = node.module.split(".")
                    top = parts[0]
                    if top in pkg_modules and top != own_key:
                        imported.add(top)
                    elif top == pkg_name and len(parts) > 1:
                        inner_parts = parts[1:]
                        for i in range(len(inner_parts), 0, -1):
                            candidate = ".".join(inner_parts[:i])
                            if candidate in pkg_modules and candidate != own_key:
                                imported.add(candidate)
                                break
                elif node.level > 0 and node.module is not None:
                    # Relative import: resolve to full dotted path
                    # own_key "voxd.music.on_handler" + "from .loop" → "voxd.music.loop"
                    parent_parts = own_key.rsplit(".", node.level)
                    parent = parent_parts[0] if len(parent_parts) > 1 else ""
                    resolved = f"{parent}.{node.module}" if parent else node.module
                    # Try the full resolved path and progressively shorter prefixes
                    for candidate in (resolved, node.module.split(".")[0]):
                        if candidate in pkg_modules and candidate != own_key:
                            imported.add(candidate)
                            break
                elif node.level > 0 and node.module is None:
                    # "from . import foo" — resolve each name relative to parent
                    parent_parts = own_key.rsplit(".", node.level)
                    parent = parent_parts[0] if len(parent_parts) > 1 else ""
                    for alias in node.names:
                        resolved = f"{parent}.{alias.name}" if parent else alias.name
                        for candidate in (resolved, alias.name):
                            if candidate in pkg_modules and candidate != own_key:
                                imported.add(candidate)
                                break
        return imported

    # ---- import graph for circular detection ----

    def _build_import_graph(
        self,
        directory: Path,
        pkg_modules: frozenset[str],
    ) -> dict[str, set[str]]:
        """Build a directed graph of internal imports using module keys."""
        pkg_name = directory.name
        graph: dict[str, set[str]] = {}
        for py_file in sorted(directory.rglob("*.py")):
            if py_file.name.startswith("."):
                continue
            key = self._module_key(py_file, directory)
            try:
                source = py_file.read_text()
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            graph[key] = self._parse_internal_imports(tree, key, pkg_modules, pkg_name)
        return graph

    @staticmethod
    def _tarjan_scc(graph: dict[str, set[str]]) -> list[set[str]]:
        """Return the strongly connected components of graph (Tarjan's SCC).

        Iterative — a recursive walk would risk the interpreter's recursion
        limit on a long, linear import chain. SCC membership is a property
        of the graph alone: it is the same partition no matter what order
        neighbors are visited in. Neighbor iteration is sorted anyway, not
        raw set iteration, because str-keyed sets order by hash, which
        PYTHONHASHSEED randomizes per process — an unsorted walk would make
        the DISCOVERY and RETURN order of the SCCs (and of members within
        each SCC) flip between runs on the exact same source tree, even
        though which nodes land in which component would not.
        """
        index_of: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        on_stack: set[str] = set()
        tarjan_stack: list[str] = []
        sccs: list[set[str]] = []
        next_index = 0

        for root in sorted(graph):
            if root in index_of:
                continue

            index_of[root] = next_index
            lowlink[root] = next_index
            next_index += 1
            tarjan_stack.append(root)
            on_stack.add(root)
            # Explicit call stack standing in for the recursive strongconnect:
            # each frame is (node, its sorted neighbors, the next one to visit).
            work: list[tuple[str, list[str], int]] = [
                (root, sorted(graph.get(root, ())), 0)
            ]

            while work:
                node, neighbors, i = work[-1]
                if i < len(neighbors):
                    work[-1] = (node, neighbors, i + 1)
                    neighbor = neighbors[i]
                    if neighbor not in graph:
                        continue
                    if neighbor not in index_of:
                        index_of[neighbor] = next_index
                        lowlink[neighbor] = next_index
                        next_index += 1
                        tarjan_stack.append(neighbor)
                        on_stack.add(neighbor)
                        work.append((neighbor, sorted(graph.get(neighbor, ())), 0))
                    elif neighbor in on_stack:
                        lowlink[node] = min(lowlink[node], index_of[neighbor])
                    continue

                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == index_of[node]:
                    component: set[str] = set()
                    while True:
                        member = tarjan_stack.pop()
                        on_stack.discard(member)
                        component.add(member)
                        if member == node:
                            break
                    sccs.append(component)

        return sccs

    @staticmethod
    def _find_cycle_members(graph: dict[str, set[str]]) -> set[str]:
        """Return every node that participates in any cycle.

        A node is in a cycle iff its SCC (Tarjan) has two or more members,
        or it has a self-loop. A prior DFS-path approach recorded cycle
        membership only on a back-edge into a GRAY (on-stack) node, so a
        node reached solely along an already-BLACK path into the same
        cycle was silently dropped: edges A->B, A->C, B->A, C->B are all
        one cycle, but a DFS visiting B first reports only {A, B} because
        C is never revisited once B has gone black. SCC membership doesn't
        depend on traversal order, so it can't under-report this way.
        """
        in_cycle: set[str] = set()
        for component in CouplingScorer._tarjan_scc(graph):
            if len(component) >= 2:
                in_cycle.update(component)
                continue
            (node,) = component
            if node in graph.get(node, ()):
                in_cycle.add(node)
        return in_cycle

    # ---- scoring ----

    @staticmethod
    def _score_file(
        path: Path,
        pkg_modules: frozenset[str],
        pkg_name: str = "",
    ) -> dict[str, float | int | str]:
        source = path.read_text()
        return ModuleCouplingMetrics(str(path), source, pkg_modules, pkg_name).compute()

    def _score_directory(
        self,
        directory: Path,
    ) -> list[dict[str, float | int | str]]:
        pkg_modules = self._discover_package_modules(directory)
        pkg_name = directory.name
        results: list[dict[str, float | int | str]] = []
        for py_file in sorted(directory.rglob("*.py")):
            if py_file.name.startswith("."):
                continue
            try:
                results.append(self._score_file(py_file, pkg_modules, pkg_name))
            except SyntaxError as e:
                results.append({"file": str(py_file), "error": str(e)})

        # Circular import detection — use module keys, not bare stems
        graph = self._build_import_graph(directory, pkg_modules)
        cycle_members = self._find_cycle_members(graph)
        for r in results:
            if "error" in r:
                continue
            fpath = str(r["file"])
            key = self._module_key(Path(fpath), directory)
            r["circular_imports"] = 1 if key in cycle_members else 0

        # Package-level scoring
        self._package_results = self._score_packages(directory, graph)

        return results

    # ---- package-level scoring ----

    def _score_packages(
        self,
        directory: Path,
        graph: dict[str, set[str]],
    ) -> list[dict[str, float | int | str]]:
        """Compute metrics for each sub-package within the scored directory."""
        packages: list[dict[str, float | int | str]] = []

        # Find all packages at every level (dirs with __init__.py)
        sub_pkgs: list[Path] = []
        for item in sorted(directory.rglob("__init__.py")):
            pkg_dir = item.parent
            if pkg_dir != directory:
                sub_pkgs.append(pkg_dir)

        if not sub_pkgs:
            return packages

        for pkg_dir in sub_pkgs:
            rel = pkg_dir.relative_to(directory)
            pkg_name = str(rel).replace("/", ".")

            # Modules belonging to this package (match key prefix)
            pkg_module_keys = {
                k for k in graph if k == pkg_name or k.startswith(f"{pkg_name}.")
            }

            # Package efferent coupling: sibling packages this package imports from
            sibling_pkgs_imported: set[str] = set()
            for mod_key in pkg_module_keys:
                for dep in graph.get(mod_key, set()):
                    dep_top = dep.split(".")[0]
                    if dep_top != pkg_name and dep_top not in pkg_module_keys:
                        sibling_pkgs_imported.add(dep_top)
            pkg_efferent = len(sibling_pkgs_imported)

            # Intra-package coupling: edges between modules within the package
            intra_edges = 0
            for mod_key in pkg_module_keys:
                for dep in graph.get(mod_key, set()):
                    if dep in pkg_module_keys or dep == pkg_name:
                        intra_edges += 1
            n_modules = len(pkg_module_keys)
            max_edges = n_modules * (n_modules - 1) if n_modules > 1 else 1
            intra_density = round(intra_edges / max_edges, 3) if max_edges > 0 else 0.0

            # Package interface width: public names in __init__.py
            init_file = pkg_dir / "__init__.py"
            pkg_interface = 0
            if init_file.exists():
                try:
                    source = init_file.read_text()
                    tree = ast.parse(source, filename=str(init_file))
                    for node in ast.iter_child_nodes(tree):
                        if isinstance(node, ast.Assign):
                            for target in node.targets:
                                if (
                                    isinstance(target, ast.Name)
                                    and target.id == "__all__"
                                    and isinstance(node.value, (ast.List, ast.Tuple))
                                ):
                                    pkg_interface = len(node.value.elts)
                    if pkg_interface == 0:
                        for node in ast.iter_child_nodes(tree):
                            if (
                                isinstance(node, ast.ImportFrom)
                                and node.module is not None
                            ):
                                for alias in node.names:
                                    if not alias.name.startswith("_"):
                                        pkg_interface += 1
                except SyntaxError:
                    pass

            # Package cohesion: fraction of modules that import at least one sibling
            modules_with_internal_dep = 0
            for mod_key in pkg_module_keys:
                for dep in graph.get(mod_key, set()):
                    if dep in pkg_module_keys and dep != mod_key:
                        modules_with_internal_dep += 1
                        break
            pkg_cohesion = (
                round(modules_with_internal_dep / n_modules, 3)
                if n_modules > 0
                else 0.0
            )

            packages.append(
                {
                    "package": pkg_name,
                    "modules": n_modules,
                    "pkg_efferent_coupling": pkg_efferent,
                    "pkg_interface_width": pkg_interface,
                    "pkg_intra_density": intra_density,
                    "pkg_cohesion": pkg_cohesion,
                }
            )

        return packages

    @property
    def package_results(self) -> list[dict[str, float | int | str]]:
        return self._package_results if hasattr(self, "_package_results") else []

    def print_packages(self) -> None:
        """Print package-level metrics."""
        pkgs = self.package_results
        if not pkgs:
            return
        _writeln("\n--- Package-level metrics ---")
        _writeln(
            f"\n  {'Package':<20} {'Modules':>8} {'Ext Deps':>9} "
            f"{'Interface':>10} {'Density':>8} {'Cohesion':>9}",
        )
        _writeln("  " + "-" * 68)
        for p in pkgs:
            _writeln(
                f"  {p['package']:<20} {p['modules']:>8} "
                f"{p['pkg_efferent_coupling']:>9} "
                f"{p['pkg_interface_width']:>10} "
                f"{p['pkg_intra_density']:>8.3f} "
                f"{p['pkg_cohesion']:>9.3f}",
            )

    def _aggregate(self) -> dict[str, float]:
        numeric_keys = list(self._thresholds)
        agg: dict[str, list[float]] = {k: [] for k in numeric_keys}
        for r in self._results:
            if "error" in r:
                continue
            for k in numeric_keys:
                if k in r:
                    agg[k].append(float(r[k]))
        summary: dict[str, float] = {}
        for k, values in agg.items():
            if not values:
                continue
            max_metrics = (
                "efferent_coupling",
                "public_names",
                "circular_imports",
                "max_lcom",
            )
            if k in max_metrics:
                summary[k] = max(values)
            else:
                summary[k] = round(sum(values) / len(values), 3)
        return summary

    def print_table(self) -> None:
        summary = self.summary
        grades = self.grades
        _writeln(f"\n{'Metric':<28} {'Value':>8} {'Target':>10} {'Grade':>6}")
        _writeln("-" * 56)
        for k in self._thresholds:
            if k in summary:
                op, target_val = self._thresholds[k]
                g = grades[k]
                marker = "  " if g == "PASS" else " *"
                _writeln(f"{k:<28} {summary[k]:>8.2f} {op} {target_val:<8} {g}{marker}")

    def print_per_file(self) -> None:
        _writeln("\n--- Per-file breakdown ---")
        for r in self._results:
            fpath = str(r.get("file", "?"))
            _writeln(f"\n  {fpath}")
            for k, v in r.items():
                if k == "file":
                    continue
                if k in self._thresholds:
                    g = "PASS" if self._check(k, float(v), fpath) else "FAIL"
                    _writeln(f"    {k:<26} {v:>8} {g}")

    def to_json(self) -> str:
        output = {
            "per_file": self._results,
            "aggregate": self.summary,
            "grades": self.grades,
            "thresholds": {k: f"{op} {v}" for k, (op, v) in self._thresholds.items()},
        }
        return json.dumps(output, indent=2)


# ------------------------------------------------------------------
# Ratchet: baseline persistence, regression checking, audit logging
# ------------------------------------------------------------------


class CouplingRatchet:
    """Baseline persistence, regression checking, and audit logging."""

    _baseline_path: Path
    _audit_path: Path
    _baseline: dict[str, dict[str, float]]

    BASELINE_FILE: ClassVar[str] = ".oo-coupling-baseline.json"
    AUDIT_FILE: ClassVar[str] = ".oo-coupling-audit.jsonl"

    METRIC_KEYS: ClassVar[tuple[str, ...]] = tuple(CouplingScorer.THRESHOLDS)

    def __new__(cls, root: Path | None = None) -> Self:
        self = super().__new__(cls)
        base = root if root is not None else Path.cwd()
        self._baseline_path = base / cls.BASELINE_FILE
        self._audit_path = base / cls.AUDIT_FILE
        self._baseline = self._load_baseline()
        return self

    @property
    def has_baseline(self) -> bool:
        return self._baseline_path.exists()

    @property
    def baseline(self) -> dict[str, dict[str, float]]:
        return self._baseline

    # ---- baseline I/O ----

    def _load_baseline(self) -> dict[str, dict[str, float]]:
        if not self._baseline_path.exists():
            return {}
        text = self._baseline_path.read_text()
        raw: dict[str, dict[str, float]] = json.loads(text)
        return raw

    def _save_baseline(self, data: dict[str, dict[str, float]]) -> None:
        sorted_data = dict(sorted(data.items()))
        self._baseline_path.write_text(
            json.dumps(sorted_data, indent=2) + "\n",
        )
        self._baseline = sorted_data

    # ---- git helpers ----

    @staticmethod
    def _git_commit_short() -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    @staticmethod
    def _git_touched_files(base_ref: str = "HEAD~1") -> list[str] | None:
        """Return repo-relative paths changed between ``base_ref`` and HEAD.

        ``"HEAD~1"`` here is this *function's* own narrow fallback, used
        only by a direct, non-CLI caller that passes no ``base_ref`` (tests
        construct one explicitly to reproduce the old bug -- see
        ``tests/oo_coupling/test_push_base_ref.py``). The CLI entry point
        (``main()``) never relies on it: when ``--base-ref`` is omitted from
        argv, ``main()`` resolves ``merge-base(origin/main, HEAD)`` itself
        via ``_resolve_default_base_ref`` -- the same default
        ``oo_score.py``'s ``GitRepo.resolve_base`` already computes for its
        own bare ``--check`` -- so a plain local ``make check-coupling``
        scores the whole fork-to-HEAD range, not just the last commit.
        CI still overrides explicitly on both triggers, as
        belt-and-suspenders against this function's own local fallback, not
        because the CLI default is wrong: the push-to-main job passes
        ``github.event.before`` (the pre-push tip of main) so a push landing
        more than one commit is diffed as the whole ``before..after`` range
        -- otherwise a regression in an earlier commit of a multi-commit
        push would never appear in a single-commit range and would pass
        trivially. The pull_request job passes its own computed
        ``merge-base(origin/main, HEAD)`` for the identical reason on a
        multi-commit PR.
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{base_ref}..HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return [line for line in result.stdout.strip().splitlines() if line]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    @staticmethod
    def _git_renamed_files(base_ref: str = "HEAD~1") -> set[str]:
        """Return new-path side of *pure* renames between ``base_ref`` and HEAD.

        Same ``base_ref`` default and override rationale as
        ``_git_touched_files`` -- the rename set must be scoped to the same
        range the touched-file set is scoped to, or a rename in an earlier
        push commit could be excluded from ``touched`` (correct) while its
        content regression is missed entirely (incorrect: renames+regresses
        elsewhere in a multi-commit push must still be scored).

        Uses ``--name-status`` rather than ``--name-only`` because
        ``--diff-filter=R`` matches *any* rename git detects, including one
        where the content also changed (``R82`` == 82% similar, not 100%) --
        ``--name-only`` collapses that distinction away, so a renamed-and-
        modified file (a genuine regression candidate) would be subtracted
        from ``touched`` right alongside a true no-op rename. Only ``R100``
        (100% similarity -- byte-identical content) has nothing to score;
        anything below that keeps its new path in the touched set.
        """
        try:
            result = subprocess.run(
                [
                    "git",
                    "diff",
                    "-M",
                    "--diff-filter=R",
                    "--name-status",
                    f"{base_ref}..HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                renamed: set[str] = set()
                for line in result.stdout.strip().splitlines():
                    if not line:
                        continue
                    # Rename lines are "R<score>\t<old>\t<new>" -- the score
                    # is a variable-width percentage (e.g. "R100", "R82").
                    parts = line.split("\t")
                    if len(parts) != 3:
                        continue
                    status, _old_path, new_path = parts
                    if status == "R100":
                        renamed.add(new_path)
                return renamed
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return set()

    @staticmethod
    def _resolve_default_base_ref() -> str:
        """Return the base ref the CLI diffs against when ``--base-ref`` is
        never passed at all.

        ``merge-base(origin/main, HEAD)`` -- the identical default
        ``oo_score.py``'s ``GitRepo.resolve_base`` already computes for its
        own bare ``--check`` -- so a plain local ``make check-coupling``
        scores the whole fork-to-HEAD range a real PR would carry, not just
        the narrower ``HEAD~1..HEAD`` last-commit range the old default
        silently kept: a within-cap regression landed in an earlier commit
        of a multi-commit branch, never re-touched by a later one, passed
        locally and only failed in CI, which always overrides explicitly
        (see ``_git_touched_files``).

        Falls back to ``"HEAD~1"`` -- the old, narrower default -- in two
        cases:

        1. Merge-base cannot resolve: no ``origin/main`` fetched, no
           ``origin`` remote, or no common history with ``origin/main``.
        2. The merge-base *is* HEAD -- i.e. HEAD is an ancestor of (or equal
           to) ``origin/main`` and carries no commits ahead of it, so
           ``merge-base..HEAD`` is an empty range that would score nothing.
           This is the shape of a push whose ``origin/main`` was just fetched
           to the pushed tip (``ratchets.yml``'s bare ``make check-coupling``
           on an all-zeros ``github.event.before``), and of any local
           checkout sitting on or behind ``origin/main``. Falling back to
           ``HEAD~1`` scores the last commit -- exactly the prior default's
           behavior -- instead of vacuously passing.

        Either fallback can never regress local usage below what the old
        unconditional ``HEAD~1`` default already risked; the merge-base
        result only widens the common, resolvable, commits-ahead case.
        """
        try:
            merge_base = subprocess.run(
                ["git", "merge-base", "origin/main", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "HEAD~1"
        if merge_base.returncode != 0:
            return "HEAD~1"
        resolved = merge_base.stdout.strip()
        head_sha = head.stdout.strip() if head.returncode == 0 else ""
        if not resolved or resolved == head_sha:
            return "HEAD~1"
        return resolved

    # ---- metric comparison helpers ----

    @staticmethod
    def _threshold_for(metric: str, filepath: str = "") -> tuple[str, float]:
        """Return the (op, target) absolute threshold for ``metric`` on ``filepath``.

        ``__main__.py`` gets ``CouplingScorer.MAIN_THRESHOLDS``' relaxed caps
        where one is defined for the metric (``efferent_coupling <= 15``,
        ``public_names <= 100``); every other metric, and every other
        filepath, uses ``CouplingScorer.THRESHOLDS``. Shared by
        ``_meets_threshold`` (the pass/fail check) and every caller that
        formats a threshold into a diagnostic message, so a refusal message
        can never cite the default cap for a file that was actually judged
        against the relaxed one.
        """
        thresholds = CouplingScorer.THRESHOLDS
        is_main = filepath.endswith("__main__.py")
        if is_main and metric in CouplingScorer.MAIN_THRESHOLDS:
            thresholds = {**thresholds, **CouplingScorer.MAIN_THRESHOLDS}
        return thresholds[metric]

    @staticmethod
    def _meets_threshold(metric: str, value: float, filepath: str = "") -> bool:
        """Return True if value meets the absolute threshold."""
        op, target = CouplingRatchet._threshold_for(metric, filepath)
        if op == ">=":
            return value >= target
        if op == "<=":
            return value <= target
        return value == target

    @staticmethod
    def _is_better_or_equal(
        metric: str,
        current: float,
        baseline_val: float,
    ) -> bool:
        """Return True if current is at least as good as baseline."""
        op, target = CouplingScorer.THRESHOLDS[metric]
        if op == ">=":
            return current >= baseline_val
        if op == "<=":
            return current <= baseline_val
        return abs(current - target) <= abs(baseline_val - target)

    @staticmethod
    def _is_strictly_better(
        metric: str,
        current: float,
        baseline_val: float,
    ) -> bool:
        """Return True if current is strictly better than baseline."""
        op, target = CouplingScorer.THRESHOLDS[metric]
        if op == ">=":
            return current > baseline_val
        if op == "<=":
            return current < baseline_val
        return abs(current - target) < abs(baseline_val - target)

    @staticmethod
    def _over_cap_and_regressed(
        current: dict[str, float],
        baseline_entry: dict[str, float] | None,
        filepath: str,
    ) -> list[tuple[str, float]]:
        """Return the ``(metric, value)`` pairs that refuse a rebaseline bless.

        A metric refuses the bless only when it BOTH strictly exceeds its
        absolute PL-CU-1 cap AND regressed against ``baseline_entry`` (the
        file's existing committed baseline row, keyed under whatever key
        this bless will be recorded on -- see ``canonical_key`` at the call
        site). An over-cap metric that is unchanged or improved versus its
        baseline is carried forward untouched, not refused -- this is what
        lets a file with a pre-existing, non-regressing over-cap metric (one
        ``check()``/``update()`` already grandfather by their own
        no-regression rule) still receive a bless for a *different* metric's
        genuine within-cap regression, instead of the whole file being
        blocked by a violation nobody is asking to change.

        ``baseline_entry`` absent (a genuinely new file, never rebaselined
        before) or missing this specific metric falls back to the strict
        rule: any value over cap refuses, exactly as if there were no prior
        value to grandfather against -- there is nothing to compare against
        that would justify carrying it forward.
        """
        refusals: list[tuple[str, float]] = []
        for metric, value in current.items():
            if CouplingRatchet._meets_threshold(metric, value, filepath):
                continue
            if baseline_entry is None or metric not in baseline_entry:
                refusals.append((metric, value))
                continue
            baseline_val = baseline_entry[metric]
            if not CouplingRatchet._is_better_or_equal(metric, value, baseline_val):
                refusals.append((metric, value))
        return refusals

    # ---- extract per-file metric dicts ----

    @staticmethod
    def _results_by_file(
        results: list[dict[str, float | int | str]],
    ) -> dict[str, dict[str, float]]:
        """Build {path: {metric: value}} from scorer results."""
        out: dict[str, dict[str, float]] = {}
        for r in results:
            if "error" in r:
                continue
            fpath = str(r["file"])
            metrics: dict[str, float] = {}
            for k in CouplingRatchet.METRIC_KEYS:
                if k in r:
                    metrics[k] = float(r[k])
            out[fpath] = metrics
        return out

    # ---- --check ----

    def check(self, scorer: CouplingScorer, base_ref: str = "HEAD~1") -> int:
        """Compare touched files (since ``base_ref``) against baseline.

        ``base_ref`` defaults to the latest commit -- see
        ``_git_touched_files`` for why the push-to-main CI job overrides it.
        An unresolvable ``base_ref`` (bad SHA, unfetched history) makes
        ``_git_touched_files`` return ``None``, which this falls back to
        treating every scored file as touched -- fail toward a broader check,
        never a silently narrower one.
        """
        if not self.has_baseline:
            _writeln("No baseline -- run --update to create one")
            return 0

        current_by_file = self._results_by_file(scorer.results)

        git_touched = self._git_touched_files(base_ref)
        scored_files = set(current_by_file)

        if git_touched is not None:
            touched = scored_files & set(git_touched)
        else:
            touched = scored_files

        # Exclude pure renames — no content changed, nothing to improve
        renamed = self._git_renamed_files(base_ref)
        touched -= renamed

        touched = {f for f in touched if f.endswith(".py")}

        if not touched:
            _writeln("No Python files touched -- trivial pass")
            return 0

        any_regression = False
        rows: list[tuple[str, str, str, str, str, str]] = []

        for fpath in sorted(touched):
            current = current_by_file.get(fpath)
            if current is None:
                continue
            baseline_entry = self._baseline.get(fpath)

            if baseline_entry is None:
                # New file — INFO, not FAIL
                for metric in self.METRIC_KEYS:
                    if metric not in current:
                        continue
                    val = current[metric]
                    rows.append((fpath, metric, "NEW", f"{val:.3f}", "--", "INFO"))
                continue

            for metric in self.METRIC_KEYS:
                if metric not in current or metric not in baseline_entry:
                    continue
                cur_val = current[metric]
                base_val = baseline_entry[metric]
                delta = cur_val - base_val

                if self._is_strictly_better(metric, cur_val, base_val):
                    grade = "IMPROVED"
                elif self._is_better_or_equal(metric, cur_val, base_val):
                    grade = "PASS"
                else:
                    grade = "REGRESSED"
                    any_regression = True

                if delta != 0.0 or grade == "REGRESSED":
                    rows.append(
                        (
                            fpath,
                            metric,
                            f"{base_val:.3f}",
                            f"{cur_val:.3f}",
                            f"{delta:+.3f}",
                            grade,
                        )
                    )

        # Print comparison table
        _writeln(
            f"\n{'File':<40} {'Metric':<26} {'Baseline':>10} "
            f"{'Current':>10} {'Delta':>8} {'Status':>10}",
        )
        _writeln("-" * 108)
        for row in rows:
            _writeln(
                f"{row[0]:<40} {row[1]:<26} {row[2]:>10} "
                f"{row[3]:>10} {row[4]:>8} {row[5]:>10}",
            )

        if not rows:
            _writeln("  (all metrics unchanged)")

        if any_regression:
            _writeln("\nFAIL: regression detected")
            return 1

        _writeln("\nPASS: no regressions")
        return 0

    # ---- --update ----

    def update(self, scorer: CouplingScorer) -> int:
        """Update baseline for files that did not regress. Return exit code."""
        current_by_file = self._results_by_file(scorer.results)
        new_baseline = dict(self._baseline)
        refused: list[tuple[str, str]] = []
        updated_count = 0
        added_count = 0

        deltas: dict[str, dict[str, list[float]]] = {}

        for fpath in sorted(current_by_file):
            current = current_by_file[fpath]
            baseline_entry = self._baseline.get(fpath)

            if baseline_entry is None:
                new_baseline[fpath] = current
                added_count += 1
                file_deltas: dict[str, list[float]] = {}
                for metric in self.METRIC_KEYS:
                    if metric in current:
                        file_deltas[metric] = [0.0, current[metric]]
                if file_deltas:
                    deltas[fpath] = file_deltas
                continue

            has_regression = False
            for metric in self.METRIC_KEYS:
                if metric not in current or metric not in baseline_entry:
                    continue
                cur_val = current[metric]
                base_val = baseline_entry[metric]
                if not self._is_better_or_equal(metric, cur_val, base_val):
                    refused.append((fpath, metric))
                    has_regression = True

            if has_regression:
                continue

            file_deltas = {}
            for metric in self.METRIC_KEYS:
                if metric not in current or metric not in baseline_entry:
                    continue
                if current[metric] != baseline_entry[metric]:
                    file_deltas[metric] = [baseline_entry[metric], current[metric]]

            new_baseline[fpath] = current
            updated_count += 1
            if file_deltas:
                deltas[fpath] = file_deltas

        # Remove deleted files
        removed_count = 0
        for fpath in list(new_baseline):
            if fpath not in current_by_file:
                del new_baseline[fpath]
                removed_count += 1

        self._save_baseline(new_baseline)

        files_improved = sum(1 for d in deltas.values() if d)

        self._append_audit(
            files_scored=len(current_by_file),
            files_improved=files_improved,
            files_regressed=len({f for f, _ in refused}),
            verdict="pass" if not refused else "fail",
            deltas=deltas,
        )

        _writeln(f"\nBaseline updated: {self._baseline_path}")
        _writeln(f"  files scored:  {len(current_by_file)}")
        _writeln(f"  files added:   {added_count}")
        _writeln(f"  files updated: {updated_count}")
        _writeln(f"  files removed: {removed_count}")

        if refused:
            _writeln(f"\n  REFUSED ({len({f for f, _ in refused})} files):")
            for fpath, metric in refused:
                _writeln(f"    {fpath}: {metric} regressed")
            return 1

        return 0

    # ---- --rebaseline ----

    def rebaseline(self, scorer: CouplingScorer) -> int:
        """Unconditionally reset the baseline to current scores."""
        current_by_file = self._results_by_file(scorer.results)
        self._save_baseline(current_by_file)
        self._append_audit(
            files_scored=len(current_by_file),
            files_improved=0,
            files_regressed=0,
            verdict="rebaseline",
            deltas={},
        )
        _writeln(f"\nBaseline reset: {self._baseline_path}")
        _writeln(f"  files scored: {len(current_by_file)}")
        return 0

    # ---- --rebaseline-files (DES-096: bounded, scoped, tool-computed bless) ----

    def rebaseline_files(
        self,
        scorer: CouplingScorer,
        paths: list[str],
        reason: str,
    ) -> int:
        """Record the recomputed baseline for the ``paths`` that clear the gate.

        The DES-096 bless: a genuinely-necessary new dependency edge that
        stays under its absolute PL-CU-1 threshold may be recorded even
        though it is a regression against the committed baseline --
        ``--update`` refuses any regression outright. Four properties keep
        this from becoming a suppression loophole: bounded (see the gate
        rule below), tool-computed (every recorded number comes from
        ``scorer``, never from an argument), scoped (only the named
        ``paths`` are touched -- every other file's baseline entry is
        untouched), and audit-logged (every bless appends an entry to
        ``.oo-coupling-audit.jsonl`` naming the ``reason`` the caller
        supplied -- the tool cannot judge "genuinely necessary first edge,"
        so the human-supplied reason plus this record are the
        accountability).

        The gate a metric must clear is OVER CAP AND REGRESSED, not over cap
        alone (see ``_over_cap_and_regressed``). ``check()``/``update()``
        already grandfather a pre-existing, unchanged-or-improved over-cap
        metric by their own no-regression rule -- refusing it again here,
        for a bless of some OTHER metric on the same file, would make one
        file's already-accepted debt block an unrelated genuinely-necessary
        edge. A metric exactly AT the cap is within-threshold and never
        reaches the gate at all. A file with no existing baseline entry (a
        genuinely new file) has nothing to grandfather against, so every
        over-cap metric on it is refused unconditionally -- the strict rule.

        The refusal is per-metric, per-file, not all-or-nothing across the
        whole call: a named file with any metric that fails the gate is
        refused -- excluded from the baseline write, reported, and never
        recorded -- while every other named file that clears its gate is
        still blessed. The same holds for a named path absent from the
        scored tree. The call returns 0 only when every named file was
        blessed; it returns 1 whenever at least one was refused, even if the
        rest were written.

        ``reason`` must be a non-blank justification for the bless; a blank
        or whitespace-only reason is refused before anything is scored,
        because an unrecorded reason turns the audit trail into just the
        numbers -- exactly the suppression-loophole risk the bounded/
        tool-computed/scoped/audit-logged properties above are meant to
        close.
        """
        if not reason.strip():
            _writeln("--rebaseline-files requires a non-blank --reason")
            return 1

        current_by_file = self._results_by_file(scorer.results)
        # A caller may name a scored file in a form that doesn't match the
        # scorer's own key byte-for-byte -- absolute vs. repo-relative, a
        # "./" prefix, a redundant "../x/.." segment -- and a path genuinely
        # in the scored tree must not be refused merely for its spelling.
        # Path.resolve() normalizes both sides to the same absolute form
        # before comparing.
        scored_index: dict[Path, str] = {
            Path(key).resolve(): key for key in current_by_file
        }
        # The scorer key and the COMMITTED BASELINE's key for the same file
        # need not be the same string. .oo-coupling-baseline.json is always
        # keyed repo-relative (check()/update() intersect it against git's
        # repo-relative touched-file output), but --rebaseline-files can be
        # invoked with an absolute --target, which makes the scorer key
        # absolute. Writing the accepted entry under the scorer's key in
        # that case would mint a SECOND, differently-shaped key for a file
        # that already has a baseline entry -- the write lands somewhere
        # check() never looks, and the bless silently fails to unblock it.
        # This index maps each EXISTING baseline key's resolved absolute
        # path back to that key, so an accepted file's entry always lands
        # on the key the baseline (and therefore check()) already uses.
        baseline_index: dict[Path, str] = {
            Path(key).resolve(): key for key in self._baseline
        }
        # This ratchet's own root -- the directory its baseline and audit
        # files live in -- is the repo root for THIS invocation, not
        # whatever the process's cwd happens to be. A file with no existing
        # baseline entry (a genuinely new file) falls back to this form,
        # matching the convention every real invocation (make check-coupling,
        # make update-coupling) already produces by scoring a target that is
        # itself relative to the repo root.
        repo_root = self._baseline_path.parent

        accepted: list[str] = []
        # Canonical key -> its recomputed metrics. Keyed separately from
        # ``current_by_file`` because the canonical key (what gets WRITTEN)
        # and the scored key (what the metrics were computed under) can
        # differ -- see ``canonical_key`` below.
        accepted_current: dict[str, dict[str, float]] = {}
        refused: list[tuple[str, str]] = []
        for requested in paths:
            scored_key = requested if requested in current_by_file else None
            resolved = Path(requested).resolve()
            if scored_key is None:
                scored_key = scored_index.get(resolved)
            if scored_key is None:
                refused.append((requested, "not found in scored tree"))
                continue
            current = current_by_file[scored_key]
            # The key this bless is RECORDED under -- and the key its
            # GRANDFATHERING comparison reads from -- is the file's existing
            # baseline key if it has one (an update, never a second key for
            # the same file), else its path relative to this ratchet's own
            # root (the shape a brand-new entry gets from a normal, repo-
            # root-relative invocation). Computed before the threshold gate
            # below because the gate needs it too.
            canonical_key = baseline_index.get(
                resolved,
                os.path.relpath(resolved, repo_root),
            )
            over_and_regressed = self._over_cap_and_regressed(
                current,
                self._baseline.get(canonical_key),
                scored_key,
            )
            if over_and_regressed:
                detail_parts: list[str] = []
                for metric, value in over_and_regressed:
                    op, target = self._threshold_for(metric, scored_key)
                    detail_parts.append(f"{metric}={value:g} exceeds {op} {target:g}")
                refused.append((requested, "; ".join(detail_parts)))
                continue
            accepted.append(canonical_key)
            accepted_current[canonical_key] = current

        if accepted:
            new_baseline = dict(self._baseline)
            deltas: dict[str, dict[str, list[float]]] = {}
            regressed_files: set[str] = set()
            improved_files: set[str] = set()
            for fpath in accepted:
                current = accepted_current[fpath]
                baseline_entry = self._baseline.get(fpath, {})
                # Every accepted file gets a full old->new record for every
                # metric it has -- unconditionally, not only the metrics
                # that moved -- so a bless whose recomputed values happen to
                # exactly match the existing baseline is still traceable in
                # the audit log rather than silently absent from ``deltas``.
                file_deltas: dict[str, list[float]] = {}
                for metric in self.METRIC_KEYS:
                    if metric not in current:
                        continue
                    old_val = baseline_entry.get(metric, 0.0)
                    new_val = current[metric]
                    file_deltas[metric] = [old_val, new_val]
                    if metric not in baseline_entry:
                        continue
                    if not self._is_better_or_equal(metric, new_val, old_val):
                        regressed_files.add(fpath)
                    elif self._is_strictly_better(metric, new_val, old_val):
                        improved_files.add(fpath)
                new_baseline[fpath] = current
                deltas[fpath] = file_deltas

            # A file with any regressed metric is counted as regressed, not
            # improved, even if another one of its metrics also improved --
            # "improved" is reserved for files whose bless recorded a pure
            # improvement, never a regression riding alongside one.
            files_improved = len(improved_files - regressed_files)

            # Audit before baseline, not after: a bless must never end up
            # recorded in the baseline but missing from the audit log (the
            # suppression-loophole shape DES-096 exists to prevent). Writing
            # the audit entry first means a failure writing the baseline
            # (e.g. disk full) still leaves a trail of what was attempted;
            # writing the baseline first would mean a failure writing the
            # audit entry leaves a silently-unlogged baseline mutation.
            # Neither write is wrapped in try/except -- a failure here
            # propagates (fails loud) rather than being swallowed.
            self._append_audit(
                files_scored=len(accepted),
                files_improved=files_improved,
                files_regressed=len(regressed_files),
                verdict="rebaseline-files",
                deltas=deltas,
                reason=reason,
            )
            self._save_baseline(new_baseline)
            _writeln(f"\nBaseline blessed for {len(accepted)} file(s):")
            _writeln(f"  {self._baseline_path}")
            for fpath in accepted:
                _writeln(f"  {fpath}")

        if refused:
            _writeln(f"\n  REFUSED ({len(refused)} file(s), nothing written for them):")
            for fpath, why in refused:
                _writeln(f"    {fpath}: {why}")

        return 1 if refused else 0

    # ---- audit log ----

    def _append_audit(
        self,
        *,
        files_scored: int,
        files_improved: int,
        files_regressed: int,
        verdict: str,
        deltas: dict[str, dict[str, list[float]]],
        # Only "rebaseline-files" (DES-096) requires a caller-supplied
        # justification; "update" and "rebaseline" score the whole target
        # mechanically and have no per-invocation reason to record.
        reason: str | None = None,
    ) -> None:
        commit = self._git_commit_short()
        entry: dict[str, object] = {
            "ts": datetime.datetime.now(datetime.UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ",
            ),
            "commit": commit,
            "files_scored": files_scored,
            "files_improved": files_improved,
            "files_regressed": files_regressed,
            "verdict": verdict,
        }
        # Only "rebaseline-files" entries carry a "reason" key at all --
        # "update" and "rebaseline" entries keep their legacy shape
        # byte-for-byte, with no "reason" key present (not even null).
        if reason is not None:
            entry["reason"] = reason
        entry["deltas"] = deltas
        with self._audit_path.open("a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    # ---- --log ----

    def show_log(self) -> int:
        """Print audit history. Return exit code."""
        if not self._audit_path.exists():
            _writeln("No audit log found")
            return 0

        _writeln(
            f"\n{'Timestamp':<22} {'Commit':<10} {'Scored':>7} "
            f"{'Improved':>9} {'Regressed':>10} {'Verdict':>12}",
        )
        _writeln("-" * 74)

        for line in self._audit_path.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            _writeln(
                f"{entry['ts']:<22} {entry.get('commit') or '?'!s:<10} "
                f"{entry['files_scored']:>7} {entry['files_improved']:>9} "
                f"{entry['files_regressed']:>10} {entry['verdict']:>12}",
            )
        return 0


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------


def _arg_value(flag: str) -> str | None:
    """Return the value following ``flag`` in ``sys.argv``, or ``None`` if absent."""
    if flag not in sys.argv:
        return None
    idx = sys.argv.index(flag)
    if idx + 1 >= len(sys.argv):
        _writeln(f"{flag} requires a value")
        sys.exit(1)
    return sys.argv[idx + 1]


def main() -> None:
    if len(sys.argv) < 2:
        _writeln(
            f"Usage: {sys.argv[0]} <file_or_directory> "
            f"[--json] [--threshold] [--check] [--update] [--rebaseline] "
            f"[--rebaseline-files <path>[,<path>...]] "
            f'[--reason "<text>"] [--log] [--base-ref REF]',
        )
        sys.exit(1)

    # --rebaseline-files' mode-argument validation (paths present, --reason
    # present and non-blank) runs BEFORE the target is even inspected, let
    # alone scored. A missing/blank --reason is a CLI contract violation, not
    # a scoring outcome -- it must fail with its own message before a bad
    # --target wastes a directory walk scoring the whole tree, or gets masked
    # behind the less specific "Not found" error below.
    rebaseline_paths: list[str] = []
    rebaseline_reason = ""
    if "--rebaseline-files" in sys.argv:
        raw = _arg_value("--rebaseline-files") or ""
        rebaseline_paths = [p.strip() for p in raw.split(",") if p.strip()]
        if not rebaseline_paths:
            _writeln("--rebaseline-files requires at least one path")
            sys.exit(1)
        # --reason is required: the tool cannot judge "genuinely necessary
        # first edge" -- the human-supplied reason, recorded to the audit
        # log alongside the file and its old->new values, is the
        # accountability DES-096 requires for every bless.
        rebaseline_reason = _arg_value("--reason") or ""
        if not rebaseline_reason.strip():
            _writeln("--rebaseline-files requires --reason <text>")
            sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        _writeln(f"Not found: {target}")
        sys.exit(1)

    scorer = CouplingScorer(target)
    ratchet = CouplingRatchet()

    if "--check" in sys.argv:
        # --check is the only base_ref consumer, so the merge-base default is
        # resolved only here -- resolving it before the mode dispatch would
        # spawn `git merge-base` (up to a 5s block) for --update, --log,
        # --json, and plain metric runs that never use it. --base-ref
        # overrides the default; omitted, the ratchet resolves the merge-base
        # of origin/main and HEAD itself -- the same default oo_score.py's
        # GitRepo.resolve_base already computes -- so a plain local
        # `make check-coupling` scores the whole fork-to-HEAD range, matching
        # CI's pull_request trigger, instead of only the last commit. CI
        # overrides explicitly on both triggers regardless (push-to-main
        # passes github.event.before; pull_request computes and passes its
        # own merge-base).
        base_ref = _arg_value("--base-ref") or (
            CouplingRatchet._resolve_default_base_ref()
        )
        sys.exit(ratchet.check(scorer, base_ref))
    elif "--rebaseline-files" in sys.argv:
        sys.exit(ratchet.rebaseline_files(scorer, rebaseline_paths, rebaseline_reason))
    elif "--rebaseline" in sys.argv:
        sys.exit(ratchet.rebaseline(scorer))
    elif "--update" in sys.argv:
        sys.exit(ratchet.update(scorer))
    elif "--log" in sys.argv:
        sys.exit(ratchet.show_log())
    elif "--json" in sys.argv:
        _writeln(scorer.to_json())
    else:
        scorer.print_table()
        scorer.print_packages()
        if "--threshold" in sys.argv:
            scorer.print_per_file()

    sys.exit(1 if scorer.fail_count > 0 else 0)


if __name__ == "__main__":
    main()
