"""Lux's permission rules in a checkout's project or local settings.

``lux enable`` is the operator's explicit opt-in, so it -- not plugin startup
-- grants Claude Code permission to call lux's MCP tools and slash commands
without a prompt. The rules land in the checkout's
``.claude/settings.json`` or ``.claude/settings.local.json``, never the user-global
``~/.claude/settings.json``, and ``lux disable`` removes exactly the same set
(punt-kit ``permissions.md`` §6). The ``lux-dev`` plugin's rules are never
granted: maintainers add them by hand.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self, cast, final

from punt_lux.service.activation_file import ActivationFile
from punt_lux.service.permission_rules import LUX_RULES
from punt_lux.service.repo_activation import Scope

__all__ = ["PermissionChange", "ProjectPermissions"]

# Rules an earlier lux enable granted and this one does not; grant and revoke
# both strip them. ``Bash(lux -*)`` made ``lux --version`` prompt (DES-039);
# display mode now only changes a personal preference.
_LEGACY_RULES: Final[dict[str, tuple[str, ...]]] = {
    "ask": ("Bash(lux -*)", "Bash(lux display mode:*)")
}


@dataclass(frozen=True, slots=True)
class PermissionChange:
    """What a grant or revoke did to the project's ``.claude/settings.json``.

    ``changed`` lists the rules added (grant) or removed (revoke); an empty
    tuple with no ``error`` means the file already matched. ``error`` explains
    why the file was left untouched.
    """

    changed: tuple[str, ...] = ()
    error: str = ""

    def lines(self, verb: str) -> list[str]:
        """Return a report line, or none if nothing changed."""
        if self.error:
            return [f"Permissions not changed: {self.error}"]
        if self.changed:
            rules = ", ".join(self.changed)
            return [f"Permissions {verb} .claude/settings.json: {rules}"]
        return []


@dataclass(frozen=True, slots=True)
class PermissionEdit:
    file: ActivationFile
    data: bytes | None
    changed: tuple[str, ...]

    def commit(self) -> None:
        if self.data is not None:
            self.file.write(self.data)


@final
class ProjectPermissions:
    """Add or remove :data:`LUX_RULES` in one checkout's scoped settings.

    The read-modify-write holds the tool-agnostic
    ``.settings.json.punt-import.lock`` (other punt tools edit the same file),
    follows symlinks to a user-selected settings target, inserts in order without
    reordering existing entries, and does not write when nothing changes.
    Every other key and rule in the file is preserved.
    """

    __slots__ = ("_file", "_root")

    _file: ActivationFile
    _root: Path

    def __new__(cls, root: Path | str, scope: Scope = "project") -> Self:
        """Bind the permission manager to a project root."""
        self = super().__new__(cls)
        self._root = Path(root)
        name = "settings.json" if scope == "project" else "settings.local.json"
        self._file = ActivationFile(self._root / ".claude" / name)
        return self

    def grant(self) -> PermissionChange:
        """Insert each missing Lux rule; return the rules added."""
        return self._update(add=True)

    def revoke(self) -> PermissionChange:
        """Remove every lux rule; return the rules removed."""
        return self._update(add=False)

    def report(self, *, add: bool, quiet: bool) -> None:
        """Apply the rule change and report errors even in quiet mode."""
        change = self.grant() if add else self.revoke()
        if not quiet or change.error:
            for line in change.lines("added to" if add else "removed from"):
                sys.stderr.write(f"{line}\n")
        if change.error:
            raise SystemExit(1)

    def _update(self, *, add: bool) -> PermissionChange:
        """Apply the grant or revoke under the lock, reporting any refusal."""
        try:
            with self.prepare(add=add) as edit:
                edit.commit()
                return PermissionChange(changed=edit.changed)
        except ValueError as exc:
            return PermissionChange(error=str(exc))
        except OSError as exc:
            return PermissionChange(error=exc.strerror or type(exc).__name__)

    @contextmanager
    def prepare(self, *, add: bool) -> Generator[PermissionEdit]:
        """Validate and plan a settings update while holding the settings lock."""
        if self._root.resolve() == Path.home().resolve():
            msg = (
                "the repo is the home directory, whose Claude settings are user-global"
            )
            raise ValueError(msg)
        if not add and not self._file.path.exists():
            yield PermissionEdit(self._file, None, ())
            return
        with self._file.locked():
            yield self._plan(add=add)

    def _plan(self, *, add: bool) -> PermissionEdit:
        """Edit each tier in memory and serialize only if a rule changed."""
        settings = self._read()
        changed = tuple(
            rule
            for tier, owned in LUX_RULES.items()
            for rule in self._edit(
                self._rule_list(settings, tier, create=add), owned, add=add
            )
        )
        retired = self._retire_legacy(settings)
        data = (
            (json.dumps(settings, indent=2) + "\n").encode()
            if changed or retired
            else None
        )
        return PermissionEdit(
            self._file, data, changed if add else (*changed, *retired)
        )

    @staticmethod
    def _edit(rules: list[object], owned: tuple[str, ...], *, add: bool) -> list[str]:
        """Add the missing *owned* rules to *rules*, or remove them; return those."""
        if add:
            added = [rule for rule in owned if rule not in rules]
            for rule in sorted(added):
                index = next(
                    (
                        i
                        for i, value in enumerate(rules)
                        if isinstance(value, str) and value > rule
                    ),
                    len(rules),
                )
                rules.insert(index, rule)
            return added
        removed = [rule for rule in owned if rule in rules]
        rules[:] = [rule for rule in rules if rule not in owned]
        return removed

    def _retire_legacy(self, settings: dict[str, object]) -> tuple[str, ...]:
        """Remove every legacy lux rule from *settings*; return those removed."""
        retired: tuple[str, ...] = ()
        for tier, legacy in _LEGACY_RULES.items():
            rules = self._rule_list(settings, tier, create=False)
            retired = (*retired, *(rule for rule in legacy if rule in rules))
            rules[:] = [rule for rule in rules if rule not in legacy]
        return retired

    def _read(self) -> dict[str, object]:
        """Return the parsed settings, ``{}`` when absent; refuse a non-object."""
        try:
            data: object = json.loads(self._file.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            msg = f".claude/settings.json is not valid JSON ({exc.msg})"
            raise ValueError(msg) from exc
        except UnicodeDecodeError as exc:
            msg = ".claude/settings.json is not valid UTF-8"
            raise ValueError(msg) from exc
        if not isinstance(data, dict):
            msg = ".claude/settings.json is not a JSON object"
            raise ValueError(msg)
        return cast("dict[str, object]", data)

    @staticmethod
    def _rule_list(
        settings: dict[str, object], tier: str, *, create: bool
    ) -> list[object]:
        """Return ``permissions.<tier>``, created if absent and *create*.

        A ``permissions`` or tier of the wrong type is the user's data, so it
        is reported rather than overwritten. Containers created here are only
        written when a rule changes.
        """
        permissions = settings.setdefault("permissions", {})
        if not isinstance(permissions, dict):
            msg = ".claude/settings.json 'permissions' is not an object"
            raise ValueError(msg)
        tiers = cast("dict[str, object]", permissions)
        rules = tiers.setdefault(tier, []) if create else tiers.get(tier, [])
        if not isinstance(rules, list):
            msg = f".claude/settings.json 'permissions.{tier}' is not a list"
            raise ValueError(msg)
        return cast("list[object]", rules)
