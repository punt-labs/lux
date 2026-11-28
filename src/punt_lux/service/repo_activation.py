"""Resolve the checkout and its effective Lux integration state."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from punt_lux.kernel.repo_root import RepoRoot

type Scope = Literal["project", "local"]

SHARED = Path(".punt-labs/lux")
PERSONAL = Path(".punt-labs/local/lux")


@dataclass(frozen=True, slots=True)
class ActivationState:
    enabled: bool
    deciding_file: Path
    notice: str | None = None

    def describe(self) -> str:
        state = "enabled" if self.enabled else "off"
        suffix = " (marker absent)" if not self.deciding_file.exists() else ""
        if self.deciding_file.name == "disabled":
            suffix = " (a shared guide still loads if imported)"
        line = f"Lux repo integration: {state} — {self.deciding_file}{suffix}"
        return "\n".join(filter(None, (line, self.notice)))


@dataclass(frozen=True, slots=True)
class Checkout:
    root: Path

    @classmethod
    def find(cls, start: Path) -> Self | None:
        if not start.is_absolute():
            return None
        path = RepoRoot.of("headless", start).declared_path
        return cls(Path(path).resolve()) if path is not None else None

    @classmethod
    def enabled_at(cls, start: Path) -> Self | None:
        checkout = cls.find(start)
        return checkout if checkout is not None and checkout.state().enabled else None

    @classmethod
    def resolve(cls, start: Path, *, main: bool = False) -> Self:
        try:
            result = cls._root_at(start, main=main)
        except (OSError, subprocess.TimeoutExpired) as exc:
            msg = f"Cannot resolve git checkout from {start}: {exc}"
            raise ValueError(msg) from exc
        if result.returncode == 0:
            value = os.fsdecode(result.stdout)
            if not main:
                return cls(Path(value.removesuffix("\n")).resolve())
            record, _, attributes = value.partition("\0")
            if not attributes.startswith("bare\0"):
                return cls(Path(record.removeprefix("worktree ")).resolve())
        msg = f"No git checkout at {start}"
        raise ValueError(msg)

    @staticmethod
    def _root_at(start: Path, *, main: bool) -> subprocess.CompletedProcess[bytes]:
        if main:
            return subprocess.run(
                ("/usr/bin/env", "git", "worktree", "list", "--porcelain", "-z"),
                cwd=start,
                capture_output=True,
                check=False,
                timeout=5,
            )
        return subprocess.run(
            ("/usr/bin/env", "git", "rev-parse", "--show-toplevel"),
            cwd=start,
            capture_output=True,
            check=False,
            timeout=5,
        )

    def state(self) -> ActivationState:
        for zone, file, enabled in (
            (SHARED, "opt-out", False),
            (PERSONAL, "disabled", False),
            (SHARED, "enabled", True),
            (PERSONAL, "enabled", True),
        ):
            candidate = self.root / zone / file
            if candidate.exists():
                return ActivationState(enabled, candidate)
        return ActivationState(
            enabled=False, deciding_file=self.root / SHARED / "enabled"
        )

    def require_private(self, *paths: Path) -> None:
        candidates = {
            self._relative(candidate): candidate
            for path in paths
            for candidate in (path, path.resolve())
        }
        try:
            ignored = self._ignored(tuple(candidates))
        except (OSError, subprocess.TimeoutExpired) as exc:
            msg = f"Cannot check personal paths in {self.root}: {exc}"
            raise ValueError(msg) from exc
        for relative, candidate in candidates.items():
            if relative not in ignored:
                msg = f"Personal path must be ignored and untracked: {candidate}"
                raise ValueError(msg)

    def _relative(self, path: Path) -> bytes:
        return os.fsencode(path.relative_to(self.root))

    def _ignored(self, candidates: tuple[bytes, ...]) -> set[bytes]:
        # check-ignore excludes tracked paths; ./ disambiguates pathspec magic.
        result = subprocess.run(
            ("/usr/bin/env", "git", "check-ignore", "-z", "--stdin"),
            cwd=self.root,
            input=b"".join(b"./" + candidate + b"\0" for candidate in candidates),
            capture_output=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            return set()
        return {path.removeprefix(b"./") for path in result.stdout.split(b"\0")}
