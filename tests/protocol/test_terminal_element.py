"""The terminal kind is a real wire contract, not an untested spike hook."""

from __future__ import annotations

from punt_lux.protocol.elements import element_to_dict
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.protocol.elements.terminal import TerminalElement


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
