"""BinarySweep -- the family that cures a service's stale uv-tool disk binaries.

A ``[project.scripts]`` rename leaves the old shim behind in
``~/.local/bin`` even after ``uv tool install --force`` writes the new one
under the new name -- ``uv`` only reconciles entrypoints it currently
declares, so it has no reason to remove a file it no longer manages
(``docs/architecture/binary-rename-migration.md``). This is a sibling of
:class:`~punt_lux._legacy_sweep.LegacySweep`, not a subtype: a disk shim has
no registration/config split to order around, and its central hazard is
identity (is this file even ours?), not sequencing -- see
``docs/architecture/binary-rename-migration.md`` §2.1.
:class:`~punt_lux._binary_sweep_disk.DiskBinaryLegacySweep` satisfies this
``Protocol`` structurally; see ``punt-kit/standards/oo.md`` "Families share
by protocol, not base class."
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, final, runtime_checkable

__all__ = ["BinarySweep", "BinarySweepReport", "DiskBinaryOutcome"]


@final
@dataclass(frozen=True, slots=True)
class DiskBinaryOutcome:
    """The sweep's result for one legacy disk-binary name."""

    binary_name: str
    path: str
    was_present: bool
    ownership_verified: bool
    removed: bool
    verified_clean: bool
    remediation: str

    def describe(self) -> str:
        """Return an operator-facing repair line, or ``""`` when already clean.

        When ``ownership_verified`` is ``False`` the rendered text is a
        refusal, not a fix instruction -- this codebase never deletes a file
        it could not confirm is its own shim.
        """
        if self.verified_clean:
            return ""
        if not self.ownership_verified:
            not_verified = (
                f"  legacy binary {self.path}: present but NOT verified as "
                "a punt-lux shim"
            )
            not_removed = (
                "    this file was left in place -- verify by hand before removing it"
            )
            return os.linesep.join(
                (
                    not_verified,
                    f"    inspect: {self.remediation}",
                    not_removed,
                )
            )
        return os.linesep.join(
            (
                f"  legacy binary {self.path}: still present",
                f"    fix: {self.remediation}",
            )
        )


@final
@dataclass(frozen=True, slots=True)
class BinarySweepReport:
    """The sweep's result across every legacy binary name for one service."""

    outcomes: tuple[DiskBinaryOutcome, ...]

    @property
    def all_clean(self) -> bool:
        """Return whether every legacy binary in this report ended up clean."""
        return all(outcome.verified_clean for outcome in self.outcomes)

    def describe(self) -> str:
        """Render every non-clean outcome as an operator-facing repair line."""
        lines = (outcome.describe() for outcome in self.outcomes)
        return os.linesep.join(line for line in lines if line)


@runtime_checkable
class BinarySweep(Protocol):
    """Cure and verify a service's legacy uv-tool-installed disk binaries."""

    def sweep(self) -> BinarySweepReport:
        """Attempt the cure for every legacy binary name.

        Attempts every name to completion -- never short-circuits on the
        first failure -- then raises
        :class:`~punt_lux._service_errors.ServiceMigrationError` once,
        carrying the complete report, if any name is still not clean. A
        refusal (ownership could not be verified) is fatal, the same as an
        outright removal failure -- never a silent skip.
        """
        ...

    def is_clean(self) -> bool:
        """Return whether every legacy binary is already clean, without mutating."""
        ...

    def diagnose(self) -> BinarySweepReport:
        """Return a full report of every binary's current state, without mutating.

        The non-mutating counterpart to :meth:`sweep` -- ``lux hub doctor``
        (no ``--fix``) calls this so it can render the same
        :meth:`BinarySweepReport.describe` text a failed ``sweep()`` would
        have raised, with zero side effects.
        """
        ...
