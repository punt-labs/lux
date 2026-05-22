"""Snapshot — a captured MCP tool input/response pair, persisted as JSON.

A ``Snapshot`` records the tool name, the keyword arguments passed in, the
stub configuration that fixed the display side of the interaction (so the
tool's response is deterministic without a live ``luxd``), and the response
string the tool produced under that configuration.

Replaying a snapshot means: build the same stubs, call the same tool with
the same kwargs, and compare the recorded response against the live response.
``Snapshot.matches`` is the comparator — it normalises a small, explicitly
documented set of placeholder tokens so the corpus survives non-essential
variation in future production output.

Normalisation rules (documented here so future agents do not have to
reverse-engineer them):

- The token ``<TS>`` matches any decimal number on either side. Used when a
  recorded response happens to contain a timestamp the test cannot fix.
- The token ``<PID>`` matches any integer. Used for process-ids embedded in
  ``screenshot`` paths or hub logs.

Never hide a real difference under a normalisation rule. If a tool's response
includes intrinsically variable data that cannot be pinned in the corpus, the
right answer is to exclude that tool from the corpus and file a follow-up
bead — not to add a normalisation that silently swallows the variation.

The corpus today does not rely on these tokens: every tool snapshot fixes
its variability through the stub layer. The mechanism exists so the
migration can introduce a snapshot whose response genuinely varies without
having to rewrite the comparator.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

__all__ = ["Snapshot"]


_TOKEN_PATTERNS = (
    ("<TS>", re.compile(r"-?\d+(?:\.\d+)?")),
    ("<PID>", re.compile(r"\d+")),
)


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
        """Load a snapshot from a JSON file at ``path``."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            tool=data["tool"],
            inputs=tuple((k, v) for k, v in data["inputs"]),
            setup=data["setup"],
            response=data["response"],
        )

    def to_file(self, path: Path) -> None:
        """Write the snapshot to ``path`` as pretty-printed JSON."""
        payload = {
            "tool": self.tool,
            "inputs": [list(pair) for pair in self.inputs],
            "setup": self.setup,
            "response": self.response,
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def matches(self, observed: str) -> bool:
        """Return True when ``observed`` matches this snapshot's response.

        Comparison is string-exact after token normalisation. The recorded
        response may contain placeholder tokens (``<TS>``, ``<PID>``); the
        observed response is matched against the recorded response as a
        regex where those tokens stand in for their numeric counterparts.
        Without tokens, comparison degrades to plain string equality.
        """
        if "<" not in self.response:
            return self.response == observed
        pattern = re.escape(self.response)
        for token, regex in _TOKEN_PATTERNS:
            pattern = pattern.replace(re.escape(token), regex.pattern)
        return re.fullmatch(pattern, observed) is not None

    def diff(self, observed: str) -> str:
        """Return a human-readable diff between recorded and observed responses.

        The migration's failure case is "the new code produces a different
        string than the snapshot." A unified diff is the most readable form
        of that delta — show what was expected, what came back, and let the
        reader spot the change.
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
