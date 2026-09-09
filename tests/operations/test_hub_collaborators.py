"""InboxDepth must evaluate its value at runtime, like ports.py's own aliases.

PEP-695 ``type`` aliases evaluate lazily: the names in an alias value are
resolved only when ``__value__`` is read. Any runtime introspection of the
alias (pydantic, ``typing.get_type_hints``) touches ``__value__``, so every
name an alias references must be importable at runtime, not only under
``TYPE_CHECKING``.
"""

from __future__ import annotations

from punt_lux.operations.hub_collaborators import InboxDepth


def test_inbox_depth_value_evaluates() -> None:
    assert InboxDepth.__value__ is not None
