"""JsonModalDecoder.standalone: a modal read with no tier around it."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements import ModalElement
from punt_lux.protocol.elements.modal_codec import JsonModalDecoder


def test_the_standalone_decoder_builds_the_modal_it_was_given_the_class_of() -> None:
    modal = JsonModalDecoder.standalone(ModalElement).decode(
        {"kind": "modal", "id": "m", "title": "t", "children": []}
    )

    assert (type(modal), modal.id, modal.model.visible) == (ModalElement, "m", True)


def test_the_standalone_decoder_rejects_an_unknown_child_kind() -> None:
    with pytest.raises(ValueError, match="nonesuch"):
        JsonModalDecoder.standalone(ModalElement).decode(
            {
                "kind": "modal",
                "id": "m",
                "children": [{"kind": "nonesuch", "id": "x"}],
            }
        )


def test_the_standalone_decoder_agrees_with_from_dict() -> None:
    wire = {"kind": "modal", "id": "m", "title": "t", "children": []}

    assert (
        JsonModalDecoder.standalone(ModalElement).decode(wire).to_dict()
        == ModalElement.from_dict(wire).to_dict()
    )
