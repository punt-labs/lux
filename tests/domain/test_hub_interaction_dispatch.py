"""Direct tests for the Display→Hub interaction dispatch seam."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.domain.hub import clients as clients_module
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    import pytest


def test_hub_interaction_dispatch_runs_grouped_button_handlers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("confirm")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    button = ButtonElement(id=str(element_id), label="Confirm")
    seen: list[tuple[str, str]] = []

    def _first(event: ButtonClicked) -> None:
        seen.append(("first", str(event.owner_id)))

    def _second(event: ButtonClicked) -> None:
        seen.append(("second", str(event.owner_id)))

    button.add_handler(ButtonClicked, _first)
    button.add_handler(ButtonClicked, _second)
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    mock_client = MagicMock()
    fake_registry = SimpleNamespace(get=MagicMock(return_value=mock_client))

    import punt_lux.domain.hub as hub_module

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(hub_module, "client_registry", fake_registry)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="confirm",
            ts=1.0,
            value=True,
        )
    )

    assert seen == [
        ("first", str(owner)),
        ("second", str(owner)),
    ]
    mock_client.show_async.assert_called_once()
    assert mock_client.show_async.call_args.kwargs["elements"] == [button]


def test_hub_interaction_dispatch_missing_scene_id_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``scene_id`` is None the dispatch logs a warning and returns."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None,
            element_id="btn",
            action="click",
            ts=1.0,
            value=True,
        )
    )


def test_hub_interaction_dispatch_unknown_element_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the element is not in the Hub index the dispatch returns."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id="scene",
            element_id="missing",
            action="click",
            ts=1.0,
            value=True,
        )
    )


def test_hub_interaction_dispatch_non_abc_element_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the resolved element is a wire dataclass (not ABC) the dispatch returns."""
    from collections.abc import Mapping
    from dataclasses import dataclass
    from typing import Literal, Self

    import punt_lux.domain.hub as hub_module

    @dataclass(frozen=True, slots=True)
    class _WireLeaf:
        id: str
        kind: Literal["leaf"] = "leaf"
        tooltip: str | None = None

        def to_dict(self) -> dict[str, object]:
            return {"id": self.id, "kind": self.kind}

        @classmethod
        def from_dict(cls, d: Mapping[str, object]) -> Self:
            return cls(id=str(d["id"]))

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    owner = ConnectionId("agent")
    isolated_display.register_client(owner)
    wire_leaf = _WireLeaf(id="leaf")
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=wire_leaf, parent_id=None),
    )

    fake_registry = SimpleNamespace(get=MagicMock())
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(hub_module, "client_registry", fake_registry)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id="scene",
            element_id="leaf",
            action="click",
            ts=1.0,
            value=True,
        )
    )

    fake_registry.get.assert_not_called()


def test_hub_interaction_dispatch_scene_repush_failure_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the scene re-push raises, the handler still completes."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("confirm")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    button = ButtonElement(id=str(element_id), label="Confirm")
    fired: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: fired.append("ok"))
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    mock_client = MagicMock()
    mock_client.show_async.side_effect = OSError("socket broken")
    fake_registry = SimpleNamespace(get=MagicMock(return_value=mock_client))

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(hub_module, "client_registry", fake_registry)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="confirm",
            ts=1.0,
            value=True,
        )
    )

    assert fired == ["ok"]


def test_hub_interaction_dispatch_runs_checkbox_value_changed_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("toggle")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    checkbox = CheckboxElement(id=str(element_id), label="Toggle")
    seen: list[tuple[str, bool]] = []

    def _handler(event: ValueChanged) -> None:
        seen.append(("handled", event.value))

    checkbox.add_handler(ValueChanged, _handler)
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=checkbox, parent_id=None),
    )

    mock_client = MagicMock()
    fake_registry = SimpleNamespace(get=MagicMock(return_value=mock_client))

    import punt_lux.domain.hub as hub_module

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(hub_module, "client_registry", fake_registry)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="toggle",
            event_kind="value_changed",
            ts=1.0,
            value=False,
        )
    )

    assert seen == [("handled", False)]
    mock_client.show_async.assert_called_once()
    assert mock_client.show_async.call_args.kwargs["elements"] == [checkbox]


def test_hub_interaction_dispatch_unknown_event_kind_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown event_kind logs warning and returns without firing."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("btn")
    owner = ConnectionId("agent")
    isolated_display.register_client(owner)

    button = ButtonElement(id=str(element_id), label="OK")
    fired: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: fired.append("fired"))
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="click",
            event_kind="unknown_kind",
            ts=1.0,
            value=True,
        )
    )

    assert fired == []


def test_hub_interaction_dispatch_value_changed_rejects_non_bool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-bool value on value_changed logs warning and returns."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("cb")
    owner = ConnectionId("agent")
    isolated_display.register_client(owner)

    cb = CheckboxElement(id=str(element_id), label="Toggle")
    fired: list[str] = []
    cb.add_handler(ValueChanged, lambda _e: fired.append("fired"))
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=cb, parent_id=None),
    )

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    clients_module.ClientRegistry._hub_interaction_dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="changed",
            event_kind="value_changed",
            ts=1.0,
            value="not a bool",
        )
    )

    assert fired == []
