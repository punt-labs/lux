"""``SelectionWire`` — shared wire coercion for a selection model (mode + fields).

``TableElement`` and ``TreeElement`` each compose a selection model
(``TableSelectionModel`` / ``TreeSelectionModel``) with the same wire shape: a
``SelectionMode`` cardinality plus terse-by-default set/anchor fields, omitted
at the display-only default. Both codecs (``table_codec.py`` / ``tree_codec.py``)
duplicated the mode-validation and the three-field emission verbatim; this is
the one place both live, so a third selectable kind gains the wire contract by
calling this class rather than by copying it again.
"""

from __future__ import annotations

from typing import cast, final

from punt_lux.protocol.elements.table_selection_model import SelectionMode

__all__ = ["SelectionWire"]

_MODES: frozenset[str] = frozenset({"none", "single", "multi"})


@final
class SelectionWire:
    """Stateless decode/emit of a selection model's wire fields."""

    __slots__ = ()

    @staticmethod
    def decode_mode(raw: object) -> SelectionMode:
        """Return ``raw`` as a ``SelectionMode``; raise naming the accepted set.

        Checks ``isinstance(raw, str)`` before the ``in`` membership test — an
        unhashable wire value (a list or a mapping) would otherwise raise
        ``TypeError`` from the ``frozenset`` lookup instead of the documented
        ``ValueError`` (PY-EH-1).
        """
        if not isinstance(raw, str) or raw not in _MODES:
            modes = sorted(_MODES)
            msg = f"selection_mode must be one of {modes}, got {raw!r}"
            raise ValueError(msg)
        return cast("SelectionMode", raw)

    @staticmethod
    def decode_ids(value: object, field: str) -> list[str]:
        """Return ``value`` as ``list[str]`` or raise a named ``ValueError``.

        Shared by both elements' selection-set patch setters (a table's
        ``selected_row_ids``, a tree's ``selected_node_ids``).
        """
        got = type(value).__name__
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in cast("list[object]", value)
        ):
            msg = f"{field} must be a list of strings, got {got}"
            raise ValueError(msg)
        return list(cast("list[str]", value))

    @staticmethod
    def emit_fields(
        payload: dict[str, object],
        *,
        mode: SelectionMode,
        selected_ids: frozenset[str],
        anchor_id: str,
        noun: str,
    ) -> None:
        """Write ``selection_mode`` / ``selected_{noun}_ids`` / ``anchor_{noun}_id``.

        Each is written into ``payload`` only when set — a ``none``-mode,
        empty-selection element stays terse, with no selection keys at all.
        ``noun`` is the element's selectable unit (``"row"``, ``"node"``); the
        ``selection_mode`` key name itself never varies by kind.
        """
        if mode != "none":
            payload["selection_mode"] = mode
        if selected_ids:
            payload[f"selected_{noun}_ids"] = sorted(selected_ids)
        if anchor_id:
            payload[f"anchor_{noun}_id"] = anchor_id
