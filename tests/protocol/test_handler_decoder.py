"""Wire-spec decoder tests — canonicalisation, factory dispatch, decorator chain.

The decoder turns one agent-authored wire spec into a typed
``Handler[E]`` via three stages: sugar canonicalisation, inner-factory
dispatch through a per-Element ``FactoryRegistry``, and decorator
wrapping through the process-shared ``DecoratorRegistry``. These tests
pin each stage against the spec in ``docs/oo-refactor/pr4-v2.1-design.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import ButtonHandlers, DecoratorRegistry
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol.handler_decoder import (
    FactoryRegistry,
    HandlerDecoder,
    HandlerSpec,
)


def _make_click() -> ButtonClicked:
    """Return a sample ButtonClicked event for handler dispatch tests."""
    return ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("btn"))


class _RecordingSink:
    """Minimal ``PublishSink`` for decorator chain tests."""

    _events: list[tuple[str, Mapping[str, object]]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._events = []
        return self

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        self._events.append((topic, payload))

    @property
    def topics(self) -> tuple[str, ...]:
        return tuple(topic for topic, _ in self._events)


def _button_factories() -> FactoryRegistry[ButtonClicked]:
    """Return a FactoryRegistry populated with the Button catalog."""
    registry: FactoryRegistry[ButtonClicked] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[ButtonClicked]:
        return ButtonHandlers.noop()

    registry.register("noop", _build_noop)
    return registry


# ---------------------------------------------------------------------------
# HandlerSpec.from_wire — long form


def test_long_form_extracts_event_factory_and_empty_wrap() -> None:
    spec = HandlerSpec.from_wire({"event": "click", "factory": "noop"})
    assert spec.event == "click"
    assert spec.factory == "noop"
    assert spec.factory_params == {}
    assert spec.wrap == ()


def test_long_form_carries_factory_params_excluding_reserved_keys() -> None:
    raw: Mapping[str, object] = {
        "event": "click",
        "factory": "call_model",
        "verb": "confirm",
        "wrap": [],
    }
    spec = HandlerSpec.from_wire(raw)
    assert spec.factory_params == {"verb": "confirm"}


def test_long_form_passes_wrap_entries_through_unchanged() -> None:
    raw: Mapping[str, object] = {
        "event": "click",
        "factory": "noop",
        "wrap": [{"decorator": "publish", "topics": ["a"]}],
    }
    spec = HandlerSpec.from_wire(raw)
    assert spec.wrap == ({"decorator": "publish", "topics": ["a"]},)


def test_long_form_rejects_missing_event_key() -> None:
    try:
        HandlerSpec.from_wire({"factory": "noop"})
    except ValueError as exc:
        assert "event" in str(exc)
    else:
        msg = "expected ValueError for missing event"
        raise AssertionError(msg)


def test_long_form_rejects_missing_factory_key() -> None:
    try:
        HandlerSpec.from_wire({"event": "click"})
    except ValueError as exc:
        assert "factory" in str(exc)
    else:
        msg = "expected ValueError for missing factory"
        raise AssertionError(msg)


def test_long_form_rejects_non_list_wrap() -> None:
    try:
        HandlerSpec.from_wire({"event": "click", "factory": "noop", "wrap": "publish"})
    except TypeError as exc:
        assert "wrap" in str(exc)
    else:
        msg = "expected TypeError for non-list wrap"
        raise AssertionError(msg)


def test_long_form_rejects_non_mapping_wrap_entry() -> None:
    try:
        HandlerSpec.from_wire(
            {"event": "click", "factory": "noop", "wrap": ["publish"]}
        )
    except TypeError as exc:
        assert "wrap[0]" in str(exc)
    else:
        msg = "expected TypeError for non-mapping wrap entry"
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# HandlerSpec.from_wire — sugar form


def test_publish_sugar_canonicalises_to_noop_plus_publish_decorator() -> None:
    spec = HandlerSpec.from_wire({"event": "click", "publish": ["work.saved"]})
    assert spec.event == "click"
    assert spec.factory == "noop"
    assert spec.factory_params == {}
    assert spec.wrap == ({"decorator": "publish", "topics": ["work.saved"]},)


def test_publish_sugar_rejects_non_list_topics() -> None:
    try:
        HandlerSpec.from_wire({"event": "click", "publish": "work.saved"})
    except TypeError as exc:
        assert "publish" in str(exc)
    else:
        msg = "expected TypeError for non-list publish topics"
        raise AssertionError(msg)


def test_sugar_and_long_form_in_one_spec_is_rejected() -> None:
    try:
        HandlerSpec.from_wire({"event": "click", "publish": ["x"], "factory": "noop"})
    except ValueError as exc:
        assert "sugar" in str(exc).lower() or "long form" in str(exc).lower()
    else:
        msg = "expected ValueError for mixed sugar + long form"
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# FactoryRegistry


def test_factory_registry_rejects_empty_name() -> None:
    registry: FactoryRegistry[ButtonClicked] = FactoryRegistry()

    def _build(_p: Mapping[str, object]) -> Handler[ButtonClicked]:
        return ButtonHandlers.noop()

    try:
        registry.register("", _build)
    except ValueError as exc:
        assert "name" in str(exc)
    else:
        msg = "expected ValueError for empty factory name"
        raise AssertionError(msg)


def test_factory_registry_rejects_duplicate_registration() -> None:
    registry = _button_factories()

    def _build(_p: Mapping[str, object]) -> Handler[ButtonClicked]:
        return ButtonHandlers.noop()

    try:
        registry.register("noop", _build)
    except ValueError as exc:
        assert "noop" in str(exc)
    else:
        msg = "expected ValueError for duplicate factory"
        raise AssertionError(msg)


def test_factory_registry_resolve_returns_handler_from_builder() -> None:
    registry = _button_factories()
    handler = registry.resolve("noop", {})
    assert handler(_make_click()) is None


def test_factory_registry_resolve_unknown_name_fails_with_known_set() -> None:
    registry = _button_factories()
    try:
        registry.resolve("mystery", {})
    except ValueError as exc:
        assert "mystery" in str(exc)
        assert "noop" in str(exc)
    else:
        msg = "expected ValueError for unknown factory"
        raise AssertionError(msg)


def test_factory_registry_registered_names_lists_registered_factories() -> None:
    registry = _button_factories()
    assert registry.registered_names == frozenset({"noop"})


# ---------------------------------------------------------------------------
# HandlerDecoder end-to-end


def test_decoder_long_form_produces_handler_that_runs_inner_only() -> None:
    sink = _RecordingSink()
    decoder = HandlerDecoder(
        factories=_button_factories(),
        decorators=DecoratorRegistry(sink=sink),
    )
    handler = decoder.decode_spec({"event": "click", "factory": "noop"})
    handler(_make_click())
    assert sink.topics == ()


def test_decoder_long_form_with_publish_wrap_fires_topics_after_inner() -> None:
    sink = _RecordingSink()
    decoder = HandlerDecoder(
        factories=_button_factories(),
        decorators=DecoratorRegistry(sink=sink),
    )
    raw: Mapping[str, object] = {
        "event": "click",
        "factory": "noop",
        "wrap": [{"decorator": "publish", "topics": ["work.saved"]}],
    }
    handler = decoder.decode_spec(raw)
    handler(_make_click())
    assert sink.topics == ("work.saved",)


def test_decoder_publish_sugar_and_long_form_produce_identical_behavior() -> None:
    long_sink = _RecordingSink()
    sugar_sink = _RecordingSink()
    long_decoder = HandlerDecoder(
        factories=_button_factories(),
        decorators=DecoratorRegistry(sink=long_sink),
    )
    sugar_decoder = HandlerDecoder(
        factories=_button_factories(),
        decorators=DecoratorRegistry(sink=sugar_sink),
    )
    long_spec: Mapping[str, object] = {
        "event": "click",
        "factory": "noop",
        "wrap": [{"decorator": "publish", "topics": ["t1", "t2"]}],
    }
    sugar_spec: Mapping[str, object] = {
        "event": "click",
        "publish": ["t1", "t2"],
    }
    long_decoder.decode_spec(long_spec)(_make_click())
    sugar_decoder.decode_spec(sugar_spec)(_make_click())
    assert long_sink.topics == sugar_sink.topics == ("t1", "t2")


def test_decoder_unknown_factory_fails_loud_at_decode_time() -> None:
    decoder = HandlerDecoder(
        factories=_button_factories(),
        decorators=DecoratorRegistry(sink=_RecordingSink()),
    )
    try:
        decoder.decode_spec({"event": "click", "factory": "missing"})
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        msg = "expected ValueError for unknown factory"
        raise AssertionError(msg)


def test_decoder_unknown_decorator_in_wrap_fails_loud_at_decode_time() -> None:
    decoder = HandlerDecoder(
        factories=_button_factories(),
        decorators=DecoratorRegistry(sink=_RecordingSink()),
    )
    raw: Mapping[str, object] = {
        "event": "click",
        "factory": "noop",
        "wrap": [{"decorator": "log", "level": "info"}],
    }
    try:
        decoder.decode_spec(raw)
    except ValueError as exc:
        assert "log" in str(exc)
    else:
        msg = "expected ValueError for unknown decorator"
        raise AssertionError(msg)
