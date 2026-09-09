"""The HubPorts type aliases must evaluate their values at runtime.

PEP-695 ``type`` aliases evaluate lazily: the names in an alias value are
resolved only when ``__value__`` is read. Any runtime introspection of the
alias (pydantic, ``typing.get_type_hints``) touches ``__value__``, so every
name an alias references must be importable at runtime, not only under
``TYPE_CHECKING``.
"""

from __future__ import annotations

from punt_lux.operations.ports import ElementFactoryFor, EnsureWriter, NextEvent


def test_element_factory_for_value_evaluates() -> None:
    assert ElementFactoryFor.__value__ is not None


def test_ensure_writer_value_evaluates() -> None:
    assert EnsureWriter.__value__ is not None


def test_next_event_value_evaluates() -> None:
    assert NextEvent.__value__ is not None
