"""Grep-zero guard: the retired ``LuxRestClient`` name must never resurface.

Complements ``tests/client/test_encapsulation.py``'s AST-based structural
guard (which catches import evasions ``grep`` cannot) with the literal,
whole-repo check the migration's acceptance gate names explicitly: the old
name must not appear anywhere in the shipped source, the test suite, or the
scripts a human runs directly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]
_SWEPT_DIRS = ("src", "tests", "scripts", "docs")

# Prose that is *about* the rename is exempt from the rule it describes --
# the same way a changelog entry for a rename is exempt. This module itself
# names the retired string in its own docstring and grep argument, so it is
# exempt from its own sweep for the identical reason.
#
# - library-client-encapsulation.md is the design record for this exact
#   rename; its rationale narrates the retired name throughout ("renamed
#   from LuxRestClient", "today's LuxRestClient import" in a
#   rejected-alternative). Substituting it out would corrupt sentences that
#   are about the name.
# - library.md's migration table maps each removed LuxRestClient method
#   to its LuxClient replacement -- exactly the guard's own subject
#   matter, not a regression of it.
# - system.tex, client-identity.md, one-code-path.md, and
#   client-surface-parity-design.md are historical architecture records
#   that predate this migration and describe the codebase as it stood
#   when written; rewriting their prose is out of this bead's scope
#   (docs/README.md lists them as "current" and "delivered" records
#   respectively, not concept docs, but neither is generated code this
#   bead owns).
_EXEMPT_FILES = frozenset(
    {
        Path(__file__),
        *(
            _REPO_ROOT / "docs" / rel
            for rel in (
                "architecture/library-client-encapsulation.md",
                "library.md",
                "architecture/system.tex",
                "architecture/client-identity.md",
                "architecture/one-code-path.md",
                "architecture/client-surface-parity-design.md",
            )
        ),
    }
)


def test_luxrestclient_does_not_appear_anywhere_in_the_swept_tree() -> None:
    """``grep -rn LuxRestClient`` across every swept directory returns zero hits."""
    hits: list[str] = []
    for name in _SWEPT_DIRS:
        target = _REPO_ROOT / name
        if not target.is_dir():
            continue
        result = subprocess.run(
            ["grep", "-rn", "--exclude-dir=__pycache__", "LuxRestClient", str(target)],  # noqa: S607 -- resolved via PATH; a test-time sweep, not untrusted input
            capture_output=True,
            text=True,
            check=False,
        )
        # grep exits 1 for "no match" -- the only success case here; any other
        # nonzero exit (2+) is a real grep failure, not an absence of hits.
        if result.returncode not in (0, 1):
            raise RuntimeError(f"grep failed on {target}: {result.stderr}")
        for line in result.stdout.splitlines():
            path_str = line.split(":", 1)[0]
            if Path(path_str) in _EXEMPT_FILES:
                continue
            hits.append(line)
    assert not hits, "LuxRestClient resurfaced:\n" + "\n".join(hits)
