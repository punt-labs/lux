"""The terminal kind is a real wire contract, not an untested spike hook."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements import element_to_dict
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.protocol.elements.terminal import TerminalElement
from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control_fields import ControlError


def test_terminal_round_trip_keeps_every_public_property() -> None:
    elem = TerminalElement(
        id="term-1",
        session="shell-1",
        command="/bin/zsh -l",
        height=240.0,
        tooltip="Interactive shell",
    )
    wire = element_to_dict(elem)
    restored = TerminalElement.from_dict(wire)
    assert restored.id == elem.id
    assert restored.kind == elem.kind == "terminal"
    assert restored.resolved_props() == elem.resolved_props()
    assert restored.to_dict() == wire


def test_terminal_session_defaults_to_element_id() -> None:
    elem = TerminalElement.from_dict({"kind": "terminal", "id": "term-2"})
    assert elem.session == "term-2"
    assert elem.command == ""
    assert elem.height == 0
    assert elem.tooltip is None
    assert "terminal" in DEFAULT_ABC_REGISTRY.all_kinds


@pytest.mark.parametrize("name", ["shell", "a.b_9-z", "x" * 128])
def test_terminal_and_attach_share_valid_identifiers(name: str) -> None:
    elem = TerminalElement(id="t", session=name)
    assert elem.session == AttachRequest(1, name).session
    assert elem.validate() == ()


@pytest.mark.parametrize(
    "name", ["../x", "bad name", "é", "x" * 129, "a\x00b", "\ud800"]
)
def test_terminal_rejects_the_same_invalid_identifiers_as_attach(name: str) -> None:
    with pytest.raises(ControlError):
        AttachRequest(1, name)
    with pytest.raises(ControlError):
        TerminalElement(id="t", session=name)
    with pytest.raises(ControlError):
        TerminalElement.from_dict({"kind": "terminal", "id": "t", "session": name})


@pytest.mark.parametrize("id", ["", "../default"])
def test_terminal_validates_the_default_session(id: str) -> None:
    with pytest.raises(ControlError):
        TerminalElement(id=id)


def test_validation_rechecks_a_placement_loaded_without_construction() -> None:
    elem = TerminalElement(id="t")
    object.__setattr__(elem, "_session", "../legacy")
    errors = elem.validate()
    assert len(errors) == 1
    assert errors[0].element_id == "t"
    assert "identifier" in errors[0].message
