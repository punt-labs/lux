"""Server-side table compositions — the show_table conveniences built as objects.

``target.md``: "the Hub decodes or constructs typed UI objects." A convenience
like ``show_table`` is a Hub-side app that *constructs* its UI as element
instances rather than shipping a wire dict, because its chrome (a search box, a
combo, a detail panel) is composed from primitives whose Hub-side filter and
detail handlers hold shared state (``FilteredTableModel``) spanning sibling
elements — state that a per-element wire decoder cannot wire. The whole
composition is one group root, so it pickles as one blob and its shared
references survive the Hub→Display crossing (DES-040; see table-design.md §6.1).
"""

from __future__ import annotations

from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.compositions.table_composition import (
    TableComposition,
    TableCompositionSpec,
)

__all__ = ["FilteredTableModel", "TableComposition", "TableCompositionSpec"]
