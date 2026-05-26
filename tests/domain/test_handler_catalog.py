"""Handler catalog scaffolding — per-Element factories, decorators, verbs.

The catalog modules under ``domain.handlers`` publish the bounded
vocabulary the wire spec may name. These tests pin the catalog's
behavior independent of any wire-spec decoding (which is exercised in
``tests/protocol/test_handler_decoder.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import ClassVar, Self

from punt_lux.domain.handlers import (
    BoundVerb,
    ButtonHandlers,
    DecoratorRegistry,
    DialogHandlers,
    PublishDecorator,
)
from punt_lux.domain.handlers.verb_vocabulary import VerbVocabulary
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked


def _make_click() -> ButtonClicked:
    """Return a sample ButtonClicked event for handler dispatch tests."""
    return ButtonClicked(
        scene_id=SceneId("s1"),
        element_id=ElementId("btn"),
        owner_id=ClientId("test"),
    )


class _RecordingModel:
    """Minimal ``VerbVocabulary`` for tests that exercise ``BoundVerb``."""

    _ACTIONS: ClassVar[Mapping[str, Callable[[_RecordingModel], None]]] = {
        "confirm": lambda self: self._record("confirm"),
        "cancel": lambda self: self._record("cancel"),
    }

    _seen: list[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._seen = []
        return self

    def known_verbs(self) -> frozenset[str]:
        return frozenset(self._ACTIONS)

    def invoke(self, action: str) -> None:
        action_fn = self._ACTIONS.get(action)
        if action_fn is None:
            msg = f"unknown verb: {action!r}"
            raise ValueError(msg)
        action_fn(self)

    def _record(self, verb: str) -> None:
        self._seen.append(verb)

    @property
    def seen(self) -> tuple[str, ...]:
        return tuple(self._seen)


class _RecordingSink:
    """Minimal ``PublishSink`` for decorator tests."""

    _events: list[tuple[str, Mapping[str, object]]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._events = []
        return self

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        self._events.append((topic, payload))

    @property
    def events(self) -> tuple[tuple[str, Mapping[str, object]], ...]:
        return tuple(self._events)


# ---------------------------------------------------------------------------
# ButtonHandlers catalog


def test_button_noop_handler_returns_none_and_does_nothing() -> None:
    handler = ButtonHandlers.noop()
    assert handler(_make_click()) is None


def test_button_call_model_invokes_bound_verb_once_per_event() -> None:
    model = _RecordingModel()
    verb = BoundVerb.resolve_against(model, "confirm")
    handler = ButtonHandlers.call_model(verb)
    handler(_make_click())
    assert model.seen == ("confirm",)


# ---------------------------------------------------------------------------
# DialogHandlers catalog


def test_dialog_invoke_model_drives_bound_verb_against_dialog_model() -> None:
    model = _RecordingModel()
    verb = BoundVerb.resolve_against(model, "cancel")
    handler = DialogHandlers.invoke_model(verb)
    handler(_make_click())
    assert model.seen == ("cancel",)


# ---------------------------------------------------------------------------
# Verb vocabulary


def test_verb_vocabulary_satisfied_structurally_by_recording_model() -> None:
    model = _RecordingModel()
    assert isinstance(model, VerbVocabulary)


def test_bound_verb_carries_resolved_name() -> None:
    model = _RecordingModel()
    verb = BoundVerb.resolve_against(model, "confirm")
    assert verb.verb == "confirm"


def test_bound_verb_rejects_unknown_verb_at_decode_time() -> None:
    model = _RecordingModel()
    try:
        BoundVerb.resolve_against(model, "delete")
    except ValueError as exc:
        assert "delete" in str(exc)
    else:
        msg = "expected ValueError for unknown verb"
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Decorators


def test_publish_decorator_runs_inner_then_publishes_each_topic_in_order() -> None:
    sink = _RecordingSink()
    decorator = PublishDecorator(sink=sink, topics=("a", "b"))
    inner_calls: list[ButtonClicked] = []

    def inner(event: ButtonClicked) -> None:
        inner_calls.append(event)

    wrapped = decorator.wrap(inner)
    event = _make_click()
    wrapped(event)
    assert inner_calls == [event]
    assert [topic for topic, _ in sink.events] == ["a", "b"]


def test_publish_decorator_rejects_empty_topics_list() -> None:
    sink = _RecordingSink()
    try:
        PublishDecorator(sink=sink, topics=())
    except ValueError as exc:
        assert "topic" in str(exc)
    else:
        msg = "expected ValueError for empty topics"
        raise AssertionError(msg)


def test_decorator_registry_resolves_publish_to_typed_factory() -> None:
    sink = _RecordingSink()
    registry = DecoratorRegistry(sink=sink)
    factory = registry.resolve({"decorator": "publish", "topics": ["x"]})
    inner_calls: list[object] = []

    def inner(event: object) -> None:
        inner_calls.append(event)

    wrapped = factory(inner)
    event = _make_click()
    wrapped(event)
    assert inner_calls == [event]
    assert [topic for topic, _ in sink.events] == ["x"]


def test_decorator_registry_rejects_unknown_decorator_name() -> None:
    registry = DecoratorRegistry(sink=_RecordingSink())
    try:
        registry.resolve({"decorator": "log", "level": "info"})
    except ValueError as exc:
        assert "log" in str(exc)
    else:
        msg = "expected ValueError for unknown decorator"
        raise AssertionError(msg)


def test_decorator_registry_rejects_missing_decorator_name() -> None:
    registry = DecoratorRegistry(sink=_RecordingSink())
    try:
        registry.resolve({"topics": ["x"]})
    except ValueError as exc:
        assert "decorator" in str(exc)
    else:
        msg = "expected ValueError for missing 'decorator' key"
        raise AssertionError(msg)


def test_decorator_registry_publish_requires_topics_list() -> None:
    registry = DecoratorRegistry(sink=_RecordingSink())
    try:
        registry.resolve({"decorator": "publish", "topics": "a"})
    except ValueError as exc:
        assert "topics" in str(exc)
    else:
        msg = "expected ValueError for non-list topics"
        raise AssertionError(msg)


def test_decorator_registry_registered_names_lists_publish() -> None:
    registry = DecoratorRegistry(sink=_RecordingSink())
    assert registry.registered_names == frozenset({"publish"})
