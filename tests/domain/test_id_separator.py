"""ID_SEPARATOR is one shared constant, not two independently declared copies.

Proven by behavior, not introspection: both composite-id consumers reject an
id carrying the exact character this module exports, so they agree on what
"the separator" is without either re-declaring its own private copy.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.id_separator import ID_SEPARATOR
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId


def test_it_is_the_ascii_unit_separator() -> None:
    assert ID_SEPARATOR == "\x1f"


def test_session_callback_rejects_an_id_carrying_it() -> None:
    with pytest.raises(ValidationError):
        SessionCallback(id=f"be{ID_SEPARATOR}ads", label="Beads")


def test_connection_scoped_id_rejects_a_local_id_carrying_it() -> None:
    with pytest.raises(ValueError, match="unit separator"):
        ConnectionScopedId(ConnectionId("vox-session"), f"music{ID_SEPARATOR}player")
