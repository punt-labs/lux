"""The disk policy for a product that has no legacy binaries to migrate."""

from __future__ import annotations

from typing import final

from punt_service._binary_sweep import BinarySweepReport


@final
class EmptyBinarySweep:
    """Leave disk-binary policy to the product when none was supplied."""

    __slots__ = ()

    def sweep(self) -> BinarySweepReport:
        """Return an empty successful report without touching the filesystem."""
        return self.diagnose()

    def is_clean(self) -> bool:
        """Return True: there is no product-owned disk migration."""
        return True

    def diagnose(self) -> BinarySweepReport:
        """Return the empty report for an unconfigured disk migration."""
        return BinarySweepReport(outcomes=())
