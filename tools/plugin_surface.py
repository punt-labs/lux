"""Verify the shippable plugin surface does not reach outside itself.

A marketplace install fetches ONLY the surface directory -- Claude Code's
``git-subdir`` source is a blobless clone plus ``sparse-checkout set --cone
plugin`` -- so a path that resolves outside it, or to a file the surface simply
does not ship, is a SILENT break: the hook or command runs, finds nothing, and
the feature is quietly absent on every installed copy while working perfectly in
the source tree. Nothing in ``make check`` could see that class of defect before
this gate, because the gate ran against the full tree where the target exists.

Containment is asserted on the *resolved* path, and that ordering is the whole
point. A textual ``../`` scan passes a symlink that points out of the surface,
and an existence check passes it too, because the target is right there in the
source tree; only resolving the link and comparing against the surface root
catches it. Existence is checked second, and it is the weaker claim.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Self, final

# Every plugin-root placeholder the surface can use to address its own files:
# ${CLAUDE_PLUGIN_ROOT} is what Claude Code substitutes in hooks.json, and
# PLUGIN_ROOT is what a script derives from its own location for the same job.
_PLACEHOLDER = r"\$\{?(?:CLAUDE_)?PLUGIN_ROOT\}?/"

# The trailing class is a POSITIVE one -- the characters a path can be made of --
# not a list of terminators. Enumerating terminators means every character
# forgotten becomes a false positive: an unquoted ${CLAUDE_PLUGIN_ROOT}/hooks/*.sh
# would be captured with the glob attached, and the gate would reject correct code
# for "not shipping" a file named with a literal asterisk. Matching only path
# characters stops at a quote, whitespace, and every glob metacharacter at once,
# leaving the directory prefix -- the part that can actually be verified, since a
# glob's matches cannot be checked statically.
_REFERENCE = re.compile(_PLACEHOLDER + r"[A-Za-z0-9._/-]*")

# A surface script that names the repository root is reaching for something the
# install does not contain, whatever it then appends. Narrow on purpose: these
# spellings have no legitimate use inside a plugin, so the rule cannot fire on
# correct code the way a blanket "../" scan would on `dirname "$0"/..`, which is
# how a hook correctly finds its own root.
_REPO_ROOT_VAR = re.compile(r"\$\{?(?:REPO_ROOT|PROJECT_ROOT|WORKSPACE_ROOT)\}?")

# `source x` / `. x` in a surface shell script: a real functional dependency, so
# its target has to travel with the install.
_SHELL_INCLUDE = re.compile(r"^\s*(?:source|\.)\s+[\"']?([^\"';|&\s]+)", re.MULTILINE)

_SHELL_SUFFIXES = frozenset({".sh", ".bash", ".zsh"})

# Documentation: read as prose, never sourced by a shell. See `_include_files`.
_DOC_SUFFIXES = frozenset({".md", ".markdown"})

# How much of a file to inspect when deciding whether it is text. A NUL byte in
# the first few KB is the practical marker for binary content.
_SNIFF_BYTES = 8192


@final
class Finding:
    """One reason the surface would break once installed."""

    _message: str

    def __new__(cls, message: str) -> Self:
        self = super().__new__(cls)
        self._message = message
        return self

    @property
    def message(self) -> str:
        return self._message

    def report(self) -> None:
        print(f"error: {self._message}", file=sys.stderr)


@final
class SurfaceAudit:
    """The plugin surface, and every way it can fail to stand alone."""

    _root: Path

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root.resolve()
        return self

    @property
    def root(self) -> Path:
        return self._root

    def audit(self) -> list[Finding]:
        """Every finding across all four checks, in reporting order."""
        return [
            *self._placeholder_findings(),
            *self._symlink_findings(),
            *self._include_findings(),
            *self._repo_root_findings(),
        ]

    # ------------------------------------------------------------------
    # Reading the surface
    # ------------------------------------------------------------------

    def _text_files(self) -> list[Path]:
        """Every file the surface ships that carries readable text.

        A suffix allowlist would decide this instead by what a file is *named*,
        which leaves a blind spot shaped exactly like the suffixes the list
        forgot: a hook needs no `.sh` name to be a hook — hooks.json names the
        command and Claude Code execs whatever it points at — so an
        extensionless script would be somewhere an escaping reference could
        live while the gate still called the surface clean. Read everything;
        skip only what the bytes show to be binary.
        """
        return sorted(
            p for p in self._root.rglob("*") if p.is_file() and self._is_text(p)
        )

    def _include_files(self) -> list[Path]:
        """Files whose `source` lines could be a real dependency.

        Not restricted to shell *scripts*, because a sourced fragment is not
        one: it carries no shebang and needs no exec bit, since it is read by
        the script that sources it. Gating this scan on shell classification
        would leave such a fragment's plain-relative `source "../../lib/x"`
        checked by nothing at all — it names no plugin-root placeholder and no
        repo-root variable, and it is not a symlink, so the include scan is its
        only guard.

        Documentation is the one exclusion, and it is a statement about what
        markdown *is* rather than what it is called: a command or skill file is
        prose that Claude reads, never a file a shell sources, so a `source`
        line in one is an example. Reading those as wiring would fail the gate
        on a correctly documented command.
        """
        return [p for p in self._text_files() if p.suffix.lower() not in _DOC_SUFFIXES]

    def _is_shell_script(self, path: Path) -> bool:
        """Is this a shell script, by what it contains rather than its name?

        The one place both the `source` scan and the executable-bit check ask
        the question, because both are asking the same thing. A `.sh` suffix is
        sufficient but not necessary: hooks.json names the command and Claude
        Code execs whatever it points at, so a suffixless script is still a
        script, and still ships broken at mode 0644.
        """
        if not path.is_file():
            return False
        if path.suffix in _SHELL_SUFFIXES:
            return True
        return self._is_text(path) and self._has_shell_shebang(path)

    @staticmethod
    def _is_text(path: Path) -> bool:
        with path.open("rb") as handle:
            return b"\x00" not in handle.read(_SNIFF_BYTES)

    @staticmethod
    def _has_shell_shebang(path: Path) -> bool:
        with path.open("rb") as handle:
            first = handle.readline(_SNIFF_BYTES)
        return first.startswith(b"#!") and b"sh" in first

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def references(self) -> list[str]:
        """Distinct plugin-root references, sorted, across the whole surface."""
        found: set[str] = set()
        for path in self._text_files():
            found.update(_REFERENCE.findall(self._read(path)))
        return sorted(found)

    def placeholder_is_live(self) -> bool:
        """Does hooks.json still carry a placeholder for us to extract?

        Fail closed on extraction rot: hooks.json always registers its scripts
        through the placeholder, so matching nothing there means the pattern
        above stopped working, not that the surface got clean. Without this the
        gate would pass vacuously the moment someone reformatted the file --
        the same shape as a guard whose condition can never be true.

        That property is contingent on hooks.json existing. An absent one
        answers True -- fails open -- because a plugin that registers no hooks
        legitimately has no such file, and there is no way to tell that case
        from a deleted one here. A surface WITH hooks is held to the check; a
        surface without hooks is taken at its word.
        """
        hooks = self._root / "hooks" / "hooks.json"
        if not hooks.is_file():
            return True
        return re.search(_PLACEHOLDER, self._read(hooks)) is not None

    # ------------------------------------------------------------------
    # The checks
    # ------------------------------------------------------------------

    def _contains(self, resolved: Path) -> bool:
        return resolved == self._root or resolved.is_relative_to(self._root)

    def _relative_part(self, reference: str) -> str:
        _, _, tail = reference.partition("PLUGIN_ROOT")
        return tail.lstrip("}").strip("/")

    def _placeholder_findings(self) -> list[Finding]:
        findings: list[Finding] = []
        for reference in self.references():
            relative = self._relative_part(reference)
            if not relative:
                continue
            findings.extend(self._verify(relative, reference))
        return findings

    def _verify(self, relative: str, shown: str) -> list[Finding]:
        """Containment first, then existence, then the executable bit."""
        target = (self._root / relative).resolve()
        if not self._contains(target):
            return [
                Finding(
                    f"reference escapes the plugin surface: {shown}"
                    f" (resolves to {target})"
                )
            ]
        if not target.exists():
            return [
                Finding(
                    f"reference points at a path the surface does not ship: {shown}"
                )
            ]
        # A hook Claude Code invokes as a command must be executable in the
        # installed copy; git carries the mode bit, so a non-executable script
        # here ships broken. Classification, not suffix: a hook needs no `.sh`
        # name, and `.sh` is only the most common way to spell one.
        if self._is_shell_script(target) and not os.access(target, os.X_OK):
            return [Finding(f"hook script is not executable: {shown}")]
        return []

    def _symlink_findings(self) -> list[Finding]:
        """A symlink out of the surface is the case a textual scan cannot see.

        Containment first, then existence — the same order, and for the same
        reason, as a placeholder reference. A link that resolves inside the
        surface onto nothing is still a broken link in every install.
        """
        findings: list[Finding] = []
        for path in sorted(self._root.rglob("*")):
            if not path.is_symlink():
                continue
            resolved = path.resolve()
            shown = f"{path.relative_to(self._root)} -> {resolved}"
            if not self._contains(resolved):
                findings.append(Finding(f"symlink escapes the plugin surface: {shown}"))
            elif not resolved.exists():
                findings.append(
                    Finding(f"symlink target is not shipped by the surface: {shown}")
                )
        return findings

    def _include_findings(self) -> list[Finding]:
        findings: list[Finding] = []
        for path in self._include_files():
            for raw in _SHELL_INCLUDE.findall(self._read(path)):
                if "$" in raw:
                    # Expanded at runtime; the variable checks below cover the
                    # spellings that could reach outside.
                    continue
                resolved = (path.parent / raw).resolve()
                shown = f"{path.relative_to(self._root)}: {raw}"
                if not self._contains(resolved):
                    findings.append(
                        Finding(f"sourced file escapes the plugin surface: {shown}")
                    )
                elif not resolved.exists():
                    findings.append(
                        Finding(f"sourced file is not shipped by the surface: {shown}")
                    )
        return findings

    def _repo_root_findings(self) -> list[Finding]:
        findings: list[Finding] = []
        for path in self._text_files():
            findings.extend(
                Finding(
                    f"surface names the repository root, which an install "
                    f"does not contain: {path.relative_to(self._root)}: {match}"
                )
                for match in _REPO_ROOT_VAR.findall(self._read(path))
            )
        return findings


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "surface",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "plugin",
        help="the shippable plugin surface directory (default: <repo>/plugin)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    surface = _parse_args(argv).surface
    if not surface.is_dir():
        print(f"error: plugin surface not found at {surface}", file=sys.stderr)
        return 2

    audit = SurfaceAudit(surface)
    if not audit.placeholder_is_live():
        print(
            "error: no plugin-root references found in hooks/hooks.json --\n"
            "       either the hook registration is broken or this script's\n"
            "       extraction pattern no longer matches it. Fix before relying\n"
            "       on this gate.",
            file=sys.stderr,
        )
        return 2

    findings = audit.audit()
    for finding in findings:
        finding.report()
    if findings:
        return 1

    count = len(audit.references())
    print(
        f"plugin-surface: {count} plugin-root reference(s) — "
        f"all resolve inside {audit.root.name}/"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
