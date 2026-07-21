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

from punt_lux.config import ConfigManager
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.config import DisplayModeState

__all__ = ["DisplayModeStore"]


@final
class DisplayModeStore:
    """The display-mode config file for one project; I/O failure becomes a fault."""

    _path: Path
    __slots__ = ("_path",)

    def __new__(cls, repo: str) -> Self:
        self = super().__new__(cls)
        self._path = Path(repo) / ".punt-labs" / "lux.md"
        return self

    def read(self) -> DisplayModeState | OpError:
        """Return the recorded display mode, or a ``fault`` on config I/O failure."""
        try:
            config = ConfigManager(config_path=self._path).read()
        except (OSError, UnicodeDecodeError) as exc:
            return self._fault(exc)
        return DisplayModeState.from_config(config.display)

    def write(self, field: str) -> OpError | None:
        """Persist the ``display`` field; return a ``fault`` on config I/O failure.

        ``None`` is the documented success contract, so the caller writes only
        when nothing failed.
        """
        try:
            ConfigManager(config_path=self._path).write_field("display", field)
        except (OSError, UnicodeDecodeError) as exc:
            return self._fault(exc)
        return None

    @staticmethod
    def _fault(exc: OSError | UnicodeDecodeError) -> OpError:
        """Map a config-file I/O failure to the engine-side ``fault`` reported out."""
        return OpError(code="fault", reason=f"display-mode config I/O failed: {exc}")
