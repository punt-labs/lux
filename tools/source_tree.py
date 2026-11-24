"""Repository-relative source discovery for the published workspace members."""

from __future__ import annotations

from pathlib import Path


class SourceTree:
    """Keep product and headless namespace portions in one module inventory."""

    def __init__(self, source: Path) -> None:
        self.roots = [source, *sorted(source.parent.glob("packages/*/src"))]

    def modules(self, namespace: str = "punt_lux") -> dict[str, Path]:
        """Index qualified names, rejecting conflicting namespace portions."""
        modules: dict[str, Path] = {}
        for root in self.roots:
            for path in sorted((root / namespace).rglob("*.py")):
                parts = path.relative_to(root).with_suffix("").parts
                name = ".".join(parts[:-1] if path.stem == "__init__" else parts)
                if name in modules:
                    raise ValueError(f"Duplicate module: {name}")
                modules[name] = path
        return modules

    def files(self, namespace: str = "punt_lux") -> dict[str, Path]:
        """Index Python files by their path within the combined namespace."""
        modules = self.modules(namespace)
        return {
            path.relative_to(root / namespace).as_posix(): path
            for root in self.roots
            for path in modules.values()
            if path.is_relative_to(root / namespace)
        }
