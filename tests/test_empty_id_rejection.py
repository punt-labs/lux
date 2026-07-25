"""Empty-id rejection at the shared decode boundary.

A non-anonymous ABC element with an empty id passed Hub decode (``require_str``
accepts ``""``) and then crashed the dual-write pump's anonymous-id synthesis
(``_with_unique_id`` cannot ``dataclasses.replace`` an ABC). ``require_id``
rejects the empty id at decode, so no such element reaches the pump. The one
anonymous-capable kind, ``separator``, decodes its id with ``optional_str`` and
is unaffected.
"""

from __future__ import annotations

from typing import Any

import pytest

from punt_lux.display_client import agent_element_factory
from punt_lux.protocol.elements import SeparatorElement

# One representative from each family that requires a real id: display leaves,
# an interactive input, and a composite. All route through ``require_id`` now.
_EMPTY_ID_WIRES: list[dict[str, Any]] = [
    {"kind": "spinner", "id": ""},
    {"kind": "markdown", "id": "", "content": "x"},
    {"kind": "image", "id": "", "path": "/a.png"},
    {"kind": "text", "id": "", "content": "x"},
    {"kind": "progress", "id": "", "fraction": 0.5},
    {"kind": "button", "id": ""},
    {"kind": "group", "id": "", "children": []},
]


@pytest.mark.parametrize("wire", _EMPTY_ID_WIRES, ids=lambda w: str(w["kind"]))
def test_empty_id_rejected_at_decode(wire: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"element.*'id'.*non-empty"):
        agent_element_factory().element_from_dict(wire)


def test_missing_id_still_rejected() -> None:
    with pytest.raises(ValueError, match=r"spinner element.*'id'"):
        agent_element_factory().element_from_dict({"kind": "spinner"})


class TestSeparatorRemainsAnonymous:
    def test_absent_id_accepted(self) -> None:
        elem = agent_element_factory().element_from_dict({"kind": "separator"})
        assert isinstance(elem, SeparatorElement)
        assert elem.id == ""

    def test_explicit_empty_id_accepted(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "separator", "id": ""}
        )
        assert isinstance(elem, SeparatorElement)
        assert elem.id == ""


def test_valid_id_still_decodes() -> None:
    elem = agent_element_factory().element_from_dict({"kind": "spinner", "id": "sp1"})
    assert elem.id == "sp1"
