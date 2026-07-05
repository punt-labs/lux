"""Tests for RemoteDispatchSpec — the interactive event-bucket value type."""

from __future__ import annotations

import dataclasses

import pytest

from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec


class TestRemoteDispatchSpec:
    def test_construction_and_field_access(self) -> None:
        spec = RemoteDispatchSpec(ButtonClicked, "confirm", "button_clicked")
        assert spec.event_type is ButtonClicked
        assert spec.action == "confirm"
        assert spec.event_kind == "button_clicked"

    def test_action_may_be_none(self) -> None:
        # None is the documented "fall back to the element id" sentinel the
        # wrap loop applies when a button carries no explicit action.
        spec = RemoteDispatchSpec(ButtonClicked, None, "button_clicked")
        assert spec.action is None

    def test_frozen_rejects_mutation(self) -> None:
        spec = RemoteDispatchSpec(ValueChanged, "changed", "value_changed")
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.action = "other"  # type: ignore[misc]  # frozen dataclass

    def test_equality_by_value(self) -> None:
        a = RemoteDispatchSpec(ButtonClicked, "confirm", "button_clicked")
        b = RemoteDispatchSpec(ButtonClicked, "confirm", "button_clicked")
        c = RemoteDispatchSpec(ValueChanged, "changed", "value_changed")
        assert a == b
        assert a != c
