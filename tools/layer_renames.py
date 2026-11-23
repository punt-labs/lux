"""Translate baseline module edges through Git-detected source renames."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Self


class LayerRenames:
    """Match the same import edge before and after a Python source file moves."""

    _modules: dict[str, str]

    def __new__(cls, name_status: str) -> Self:
        self = super().__new__(cls)
        fields = name_status.rstrip("\0").split("\0")
        pairs = zip(fields[1::3], fields[2::3], strict=True)
        self._modules = {
            cls._module(old): cls._module(new)
            for old, new in pairs
            if old.endswith(".py") and new.endswith(".py")
        }
        return self

    def apply(self, edges: frozenset[str]) -> frozenset[str]:
        """Translate only exact endpoints, never bless a new dependency."""
        return frozenset(
            " → ".join(
                self._modules.get(module, module) for module in edge.split(" → ")
            )
            for edge in edges
        )

    @staticmethod
    def _module(path: str) -> str:
        parts = PurePosixPath(path).relative_to("src").with_suffix("").parts
        return ".".join(parts).removesuffix(".__init__")
