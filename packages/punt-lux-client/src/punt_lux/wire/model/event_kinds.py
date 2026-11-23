"""``EventKind`` — the wire discriminator naming every remote-dispatched event.

The wire tag a ``RemoteEventHandlerInvocation`` carries and a
``RemoteDispatchSpec`` answers to. It spans every interactive kind — buttons,
value inputs, tab bars, headers, modals, table selections — so it lives in its
own module rather than with any one event class (PY-IC-9).
"""

from __future__ import annotations

from typing import Literal

__all__ = ["EventKind"]

type EventKind = Literal[
    "button_clicked",
    "value_changed",
    "tab_changed",
    "header_toggled",
    "modal_closed",
    "row_selection_changed",
]
