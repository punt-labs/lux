"""Capture a combined, qualified coupling graph across distribution boundaries."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from importlib.util import resolve_name
from pathlib import Path
from typing import TypedDict


class GraphSnapshot(TypedDict):
    """A location-independent module inventory and its directed import edges."""

    modules: list[str]
    edges: list[list[str]]
    sha256: dict[str, str]


class WorkspaceGraph:
    """Resolve top-level imports with the legacy ratchet's module-edge semantics."""

    def __init__(self, roots: list[Path]) -> None:
        self.modules: dict[str, Path] = {}
        for root in roots:
            for path in sorted(root.rglob("*.py")):
                parts = path.relative_to(root.parent).with_suffix("").parts
                name = ".".join(parts[:-1] if path.stem == "__init__" else parts)
                if name in self.modules:
                    raise ValueError(f"Duplicate module: {name}")
                self.modules[name] = path

    def snapshot(self) -> GraphSnapshot:
        """Return stable nodes, edges and source digests, independent of file paths."""
        edges: set[tuple[str, str]] = set()
        hashes: dict[str, str] = {}
        for name, path in self.modules.items():
            source = path.read_text()
            hashes[name] = hashlib.sha256(source.encode()).hexdigest()
            package = name if path.stem == "__init__" else name.rpartition(".")[0]
            for node in ast.iter_child_nodes(ast.parse(source)):
                candidates: list[str] = []
                if isinstance(node, ast.Import):
                    candidates.extend(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    origin = node.module or ""
                    if node.level:
                        origin = resolve_name("." * node.level + origin, package)
                    if not node.level or node.module:
                        candidates.append(origin)
                    if not node.level or not node.module:
                        candidates.extend(f"{origin}.{a.name}" for a in node.names)
                for candidate in candidates:
                    if target := self._resolve(candidate, name):
                        edges.add((name, target))
        return {
            "modules": sorted(self.modules),
            "edges": sorted([a, b] for a, b in edges),
            "sha256": dict(sorted(hashes.items())),
        }

    def _resolve(self, candidate: str, own: str) -> str | None:
        parts = candidate.split(".")
        legacy = own.split(".")[0] + "." + parts[0]
        if legacy in self.modules and legacy != own:
            return legacy
        for size in range(len(parts), 0, -1):
            target = ".".join(parts[:size])
            if target in self.modules and target != own:
                return target
        return None


def main() -> None:
    """Write a graph snapshot for the supplied package portions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("roots", nargs="+", type=Path)
    args = parser.parse_args()
    data = WorkspaceGraph(args.roots).snapshot()
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print(f"{len(data['modules'])} modules, {len(data['edges'])} edges: {args.output}")


if __name__ == "__main__":
    main()
