"""Persisted layer edges and their immutable git comparison baseline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Self

from tools.layer_renames import LayerRenames


class LayerBaseline:
    """Reject baseline additions relative to a resolved base commit."""

    _path: Path

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        return self

    def read(self, base_ref: str = "") -> frozenset[str]:
        return self._normalize(
            self._decode(self._path.read_text(encoding="utf-8")), base_ref
        )

    def check(self, edges: frozenset[str], base_ref: str) -> None:
        if not base_ref:
            try:
                base_ref = self._git("merge-base", "origin/main", "HEAD").strip()
            except subprocess.CalledProcessError:
                print("No origin/main merge base; skipping baseline growth check.")
                return
        commit = self._git(
            "rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"
        ).strip()
        if not self._git("ls-tree", "--name-only", commit, "--", self._path.name):
            print(f"No layer baseline at {base_ref}; skipping baseline growth check.")
            return
        previous = self._decode(self._git("show", f"{commit}:{self._path.name}"))
        added = edges - self._normalize(previous, commit)
        if added:
            raise ValueError(
                f"layer baseline grew vs {base_ref}: {len(added)} added edges\n"
                + "\n".join(f"  {edge}" for edge in sorted(added))
            )

    def _normalize(self, edges: frozenset[str], base_ref: str) -> frozenset[str]:
        if not base_ref:
            try:
                base_ref = self._git("merge-base", "origin/main", "HEAD").strip()
            except subprocess.CalledProcessError:
                return edges
        renames = self._git(
            "diff",
            "--name-status",
            "--find-renames",
            "--diff-filter=R",
            "-z",
            base_ref,
            "--",
            "src",
        )
        return LayerRenames(renames).apply(edges)

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self._path.parent,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def _decode(self, content: str) -> frozenset[str]:
        raw: object = json.loads(content)
        if not isinstance(raw, list) or not all(isinstance(edge, str) for edge in raw):
            raise ValueError("layer baseline must be a JSON array of edge strings")
        return frozenset(raw)
