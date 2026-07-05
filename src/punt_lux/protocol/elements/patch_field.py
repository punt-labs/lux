"""PatchField — boundary coercion for one ``apply_patch`` field (PY-EH-1)."""

from __future__ import annotations

from typing import Self

__all__ = ["PatchField"]


class PatchField:
    """Coerce a JSON-decoded ``apply_patch`` value for one named field.

    ``Element.apply_patch`` dispatches wire values straight to the
    ``_set_<field>`` setters, so each value arrives as ``object``. PY-EH-1
    demands boundary validation before assigning to a narrowly-typed
    attribute; a wrong-typed patch value is a construction bypass, so the
    coercers raise ``TypeError`` (PY-EH-2) naming the offending field.

    Binds the field name once so a setter reads as intent:
    ``self._label = PatchField("label").as_str(value)``.
    """

    _name: str

    def __new__(cls, name: str) -> Self:
        self = super().__new__(cls)
        self._name = name
        return self

    def as_str(self, value: object) -> str:
        """Return ``value`` as ``str`` or raise ``TypeError``."""
        if not isinstance(value, str):
            msg = f"{self._name} must be str, got {type(value).__name__}"
            raise TypeError(msg)
        return value

    def as_optional_str(self, value: object) -> str | None:
        """Return ``value`` as ``str | None`` or raise ``TypeError``."""
        if value is None or isinstance(value, str):
            return value
        msg = f"{self._name} must be str or None, got {type(value).__name__}"
        raise TypeError(msg)

    def as_bool(self, value: object) -> bool:
        """Return ``value`` as ``bool`` or raise ``TypeError``."""
        if not isinstance(value, bool):
            msg = f"{self._name} must be bool, got {type(value).__name__}"
            raise TypeError(msg)
        return value

    def as_number(self, value: object) -> float:
        """Return ``value`` as ``float`` or raise ``TypeError``.

        Rejects ``bool`` (a JSON ``true``/``false`` is not a fraction) and
        coerces ``int`` to ``float``, mirroring the wire boundary's
        ``ElementWireContext.require_number`` contract.
        """
        if isinstance(value, bool) or not isinstance(value, int | float):
            msg = f"{self._name} must be a number, got {type(value).__name__}"
            raise TypeError(msg)
        return float(value)
