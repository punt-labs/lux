"""Snapshot — a captured MCP tool input/response pair, persisted as JSON.

A ``Snapshot`` records the tool name, the keyword arguments passed in, the
stub configuration that fixed the display side of the interaction (so the
tool's response is deterministic without a live ``luxd``), and the response
string the tool produced under that configuration.

Replaying a snapshot means: build the same stubs, call the same tool with
the same kwargs, and compare the recorded response against the live response.

Path portability — the corpus is checked into git and replays on any
machine. Maintainer-absolute paths in inputs (e.g.
``/Users/foo/.../lux/tests/...``) would break CI replay. ``REPO_ROOT_TOKEN``
stands in for the absolute path of the project root at record time;
:meth:`Snapshot.from_file` substitutes the local root when the corpus is
loaded. Any new corpus entry whose inputs reference a host path must use
the same token; the no-absolute-paths guard test in ``test_parity.py``
defends the rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Self

__all__ = ["REPO_ROOT_TOKEN", "Snapshot", "repo_root", "substitute_paths"]


REPO_ROOT_TOKEN = "<REPO_ROOT>"


def repo_root() -> Path:
    """Return the project root — the directory containing ``tests/``."""
    return Path(__file__).resolve().parents[2]


def substitute_paths(value: object, src: str, dst: str) -> object:
    """Recursively swap ``src`` for ``dst`` inside JSON-shaped data.

    The corpus stores inputs and setups as JSON. At record time we swap the
    maintainer's absolute path for :data:`REPO_ROOT_TOKEN`; at replay time
    we swap the token for the local repo root. Both directions are pure
    structural rewrites — they leave non-string leaves alone.
    """
    if isinstance(value, str):
        return value.replace(src, dst)
    if isinstance(value, list):
        return [substitute_paths(item, src, dst) for item in value]
    if isinstance(value, dict):
        return {k: substitute_paths(v, src, dst) for k, v in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A captured MCP tool response under a fixed stub configuration.

    Attributes
    ----------
    tool:
        The dotted attribute name of the tool function on ``punt_lux.tools``
        (``"show"``, ``"display_mode"``, ...).
    inputs:
        Ordered keyword arguments passed to the tool. Stored as a tuple of
        pairs so the snapshot stays hashable and order-stable.
    setup:
        JSON-encodable description of the stub configuration the exerciser
        must build before invoking the tool. Owned by the exerciser; the
        snapshot only stores and recalls it verbatim.
    response:
        The exact string returned by the tool.
    """

    tool: str
    inputs: tuple[tuple[str, object], ...]
    setup: dict[str, object]
    response: str

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load a snapshot from a JSON file at ``path``.

        Substitutes :data:`REPO_ROOT_TOKEN` in inputs and setup for the
        local repo root so the corpus replays on any checkout.
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        local_root = str(repo_root())
        inputs_pairs = tuple(
            (str(k), substitute_paths(v, REPO_ROOT_TOKEN, local_root))
            for k, v in data["inputs"]
        )
        setup = substitute_paths(data["setup"], REPO_ROOT_TOKEN, local_root)
        if not isinstance(setup, dict):
            msg = f"snapshot setup must be a JSON object; got {type(setup).__name__}"
            raise ValueError(msg)
        return cls(
            tool=data["tool"],
            inputs=inputs_pairs,
            setup=setup,
            response=data["response"],
        )

    def to_file(self, path: Path) -> None:
        """Write the snapshot to ``path`` as pretty-printed JSON.

        Replaces the local repo root with :data:`REPO_ROOT_TOKEN` so the
        on-disk corpus is path-portable.
        """
        local_root = str(repo_root())
        inputs_pairs = [
            [k, substitute_paths(v, local_root, REPO_ROOT_TOKEN)]
            for k, v in self.inputs
        ]
        setup = substitute_paths(self.setup, local_root, REPO_ROOT_TOKEN)
        payload = {
            "tool": self.tool,
            "inputs": inputs_pairs,
            "setup": setup,
            "response": self.response,
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def matches(self, observed: str) -> bool:
        """Return True when ``observed`` exactly equals the recorded response."""
        return self.response == observed

    def diff(self, observed: str) -> str:
        """Return a human-readable diff between recorded and observed responses.

        Unified diff is the readable form of "what was expected vs what came
        back." For edge cases where unified_diff returns the empty string
        (whitespace-equivalent strings that nonetheless compare unequal),
        :meth:`describe_mismatch` is the fallback.
        """
        from difflib import unified_diff

        expected_lines = (self.response + "\n").splitlines(keepends=True)
        observed_lines = (observed + "\n").splitlines(keepends=True)
        return "".join(
            unified_diff(
                expected_lines,
                observed_lines,
                fromfile=f"{self.tool} (recorded)",
                tofile=f"{self.tool} (observed)",
            )
        )

    def describe_mismatch(self, observed: str) -> str:
        """Return a diff or, when the diff is empty, the raw repr of both sides.

        unified_diff can return ``""`` when ``self.response != observed`` is
        true at the byte level but the comparison reduces to nothing after
        line splitting (rare, but possible for whitespace-only differences).
        Callers should use this method in assertion messages so the failure
        is never silent.
        """
        diff = self.diff(observed)
        if diff:
            return diff
        return f"expected={self.response!r}\nobserved={observed!r}"
