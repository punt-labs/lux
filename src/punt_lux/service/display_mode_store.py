"""DisplayModeStore — one project's display-mode config file.

Owns the config-file path and the read/write I/O, mapping an ``OSError`` or a
``UnicodeDecodeError`` to a ``fault`` the surface reports instead of crashing.
The file is a backing resource, not the caller's request, so a failure to read or
write it is an engine-side ``fault`` (502), the same class as a malformed display
reply — never a caller error. This is the boundary catch the operation delegates
to, keeping ``DisplayModeOperations`` a thin coordinator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

from punt_lux.service.config import DEFAULT_CONFIG_PATH, ConfigManager
from punt_lux.service.repo_activation import Checkout
from punt_lux.wire.operations.common import OpError
from punt_lux.wire.operations.config import DisplayModeState

__all__ = ["DisplayModeStore"]


@final
class DisplayModeStore:
    """The display-mode config file for one project; I/O failure becomes a fault."""

    _main: Checkout | None
    _start: Path
    __slots__ = ("_main", "_start")

    def __new__(cls, repo: str) -> Self:
        self = super().__new__(cls)
        start = Path(repo).resolve()
        checkout = Checkout.find(start)
        self._start = start if checkout is None else checkout.root
        self._main = self._main_checkout(checkout)
        return self

    @staticmethod
    def _main_checkout(checkout: Checkout | None) -> Checkout | None:
        if checkout is None:
            return None
        try:
            return Checkout.resolve(checkout.root, main=True)
        except ValueError:
            return checkout

    @property
    def _root(self) -> Path:
        return self._start if self._main is None else self._main.root

    def read(self) -> DisplayModeState | OpError:
        """Return the recorded display mode, or a ``fault`` on config I/O failure."""
        try:
            config = ConfigManager.for_display(self._start, main=self._root).read()
        except (OSError, UnicodeDecodeError) as exc:
            return self._fault(exc)
        return DisplayModeState.from_config(config.display)

    def write(self, field: str) -> OpError | None:
        """Persist the ``display`` field; return a ``fault`` on config I/O failure.

        ``None`` is the documented success contract, so the caller writes only
        when nothing failed.
        """
        try:
            path = self._root / DEFAULT_CONFIG_PATH
            if self._main is not None:
                self._main.require_private(path)
            ConfigManager(config_path=path).write_field("display", field)
        except (OSError, ValueError) as exc:
            return self._fault(exc)
        return None

    @staticmethod
    def _fault(exc: OSError | ValueError) -> OpError:
        """Map a config-file I/O failure to the engine-side ``fault`` reported out."""
        return OpError(code="fault", reason=f"display-mode config I/O failed: {exc}")
