"""Wire-spec decoder for declarative handler chains.

Agents ship a JSON description of each handler an Element should run;
this module turns that description into a typed ``Handler[E]`` ready for
``Element.add_handler``. The decoder owns three concerns:

1. **Sugar canonicalisation.** Recognised sugar keys (``"publish"``) are
   rewritten into the long-form ``{"factory": "noop", "wrap": [...]}``
   shape before any dispatch happens. The long form is the single
   downstream code path; future sugar keys plug in by registering a
   canonicaliser.
2. **Inner factory dispatch.** A per-Element ``FactoryRegistry`` maps
   wire factory names (``"noop"``, ``"call_model"``) to builders that
   consume the remaining wire keys and return a typed ``Handler[E]``.
   Each Element kind ships its own registry so the same wire factory
   name can mean different things for different element kinds.
3. **Decorator chain.** Each entry in ``"wrap"`` is resolved through the
   ``DecoratorRegistry`` (process-shared because decorators like
   ``publish`` are Element-kind-agnostic) and applied innermost-first.

The result is a single ``Handler[E]`` the caller installs via
``element.add_handler(event_type, handler)``.

Domain stays free of wire shapes: the catalog modules
(``domain.handlers.button_catalog`` etc.) are typed against domain event
classes; this decoder lives in ``protocol`` because it speaks JSON. The
dependency arrow points inward — protocol imports domain, never the
reverse.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Self, cast

from punt_lux.domain.event_protocol import Event, Handler
from punt_lux.domain.handlers.decorators import DecoratorRegistry

__all__ = [
    "FactoryBuilder",
    "FactoryRegistry",
    "HandlerDecoder",
    "HandlerSpec",
]


# A factory builder consumes the remaining wire keys (everything except
# ``event``, ``factory``, and ``wrap``) and returns a typed
# ``Handler[E]``. The Element-kind's catalog publishes a registry that
# maps factory names to typed builders.
type FactoryBuilder[E: Event] = Callable[[Mapping[str, object]], Handler[E]]


class FactoryRegistry[E: Event]:
    """Per-Element-kind mapping of wire factory names to typed builders.

    Each Element kind constructs one of these at decoder-init time,
    populating it with builders bound to the kind's catalog. The
    decoder asks the registry to resolve a factory name; the registry
    fails loud on unknown names with the full known set in the message.
    """

    _builders: dict[str, FactoryBuilder[E]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._builders = {}
        return self

    def register(self, name: str, builder: FactoryBuilder[E]) -> None:
        """Register ``builder`` under ``name``. Re-registration is an error."""
        if not name:
            msg = "factory name must be a non-empty string"
            raise ValueError(msg)
        if name in self._builders:
            msg = f"factory already registered: {name!r}"
            raise ValueError(msg)
        self._builders[name] = builder

    def resolve(self, name: str, params: Mapping[str, object]) -> Handler[E]:
        """Build the typed handler for ``name`` from its wire ``params``."""
        builder = self._builders.get(name)
        if builder is None:
            known = sorted(self._builders)
            msg = f"unknown factory: {name!r} (expected one of {known})"
            raise ValueError(msg)
        return builder(params)

    @property
    def registered_names(self) -> frozenset[str]:
        """Return the factory names this registry recognises."""
        return frozenset(self._builders)


class HandlerSpec:
    """The canonicalised long-form record of a single wire handler spec.

    Sugar shapes (``{"event": "click", "publish": [...]}``) are rewritten
    into a ``HandlerSpec`` before dispatch, so the dispatch path is
    single-shape. ``HandlerSpec.from_wire`` is the only public construction
    site; it owns the sugar-recognition table.
    """

    _event: str
    _factory: str
    _factory_params: Mapping[str, object]
    _wrap: tuple[Mapping[str, object], ...]

    def __new__(
        cls,
        *,
        event: str,
        factory: str,
        factory_params: Mapping[str, object],
        wrap: tuple[Mapping[str, object], ...],
    ) -> Self:
        self = super().__new__(cls)
        self._event = event
        self._factory = factory
        self._factory_params = factory_params
        self._wrap = wrap
        return self

    @classmethod
    def from_wire(cls, raw: Mapping[str, object]) -> Self:
        """Canonicalise a wire dict into a ``HandlerSpec``.

        Recognised sugar keys are rewritten into a ``{"factory": "noop",
        "wrap": [...]}`` shape before construction. The single downstream
        code path then sees the same record whether the agent wrote
        long form or sugar.
        """
        event = raw.get("event")
        if not isinstance(event, str) or not event:
            msg = f"handler spec requires 'event' string: {raw!r}"
            raise ValueError(msg)
        # Sugar table — each recognised key produces one decorator entry
        # and forces the inner factory to ``noop``.
        sugar_entries: list[Mapping[str, object]] = []
        if "publish" in raw:
            topics_raw = raw["publish"]
            if not isinstance(topics_raw, list):
                msg = (
                    f"'publish' sugar requires a list of topics, got "
                    f"{type(topics_raw).__name__}"
                )
                raise TypeError(msg)
            topics_list = cast("list[object]", topics_raw)
            sugar_entries.append({"decorator": "publish", "topics": topics_list})
        if sugar_entries:
            # Sugar form: enforce that the agent did not also write the
            # long-form factory keys for the same event.
            if "factory" in raw or "wrap" in raw:
                msg = (
                    f"handler spec mixes sugar and long form: {raw!r}; "
                    f"use one or the other"
                )
                raise ValueError(msg)
            return cls(
                event=event,
                factory="noop",
                factory_params={},
                wrap=tuple(sugar_entries),
            )
        # Long form: factory is required, wrap is optional, all remaining
        # keys are passed to the factory builder as its params.
        factory = raw.get("factory")
        if not isinstance(factory, str) or not factory:
            msg = f"handler spec requires 'factory' string: {raw!r}"
            raise ValueError(msg)
        wrap_raw = raw.get("wrap", [])
        if not isinstance(wrap_raw, list):
            msg = f"handler 'wrap' must be a list, got {type(wrap_raw).__name__}"
            raise TypeError(msg)
        wrap_entries: list[Mapping[str, object]] = []
        for i, entry in enumerate(cast("list[object]", wrap_raw)):
            if not isinstance(entry, Mapping):
                msg = (
                    f"handler 'wrap[{i}]' must be a mapping, got {type(entry).__name__}"
                )
                raise TypeError(msg)
            wrap_entries.append(cast("Mapping[str, object]", entry))
        # Factory params are every key except the reserved ones; the
        # builder decides which subset it needs.
        reserved = {"event", "factory", "wrap"}
        params = {k: v for k, v in raw.items() if k not in reserved}
        return cls(
            event=event,
            factory=factory,
            factory_params=params,
            wrap=tuple(wrap_entries),
        )

    @property
    def event(self) -> str:
        """Return the event-name discriminator (e.g., ``"click"``)."""
        return self._event

    @property
    def factory(self) -> str:
        """Return the inner factory name."""
        return self._factory

    @property
    def factory_params(self) -> Mapping[str, object]:
        """Return the params the factory builder consumes."""
        return self._factory_params

    @property
    def wrap(self) -> tuple[Mapping[str, object], ...]:
        """Return the decorator-chain wire entries (innermost first)."""
        return self._wrap


class HandlerDecoder[E: Event]:
    """Build typed handlers for one Element kind from wire specs.

    Each Element kind constructs one decoder with its per-kind
    ``FactoryRegistry`` and the process-shared ``DecoratorRegistry``.
    ``decode_spec`` turns one wire spec into a typed ``Handler[E]`` ready
    for ``Element.add_handler``.
    """

    _factories: FactoryRegistry[E]
    _decorators: DecoratorRegistry

    def __new__(
        cls,
        *,
        factories: FactoryRegistry[E],
        decorators: DecoratorRegistry,
    ) -> Self:
        self = super().__new__(cls)
        self._factories = factories
        self._decorators = decorators
        return self

    def decode_spec(self, raw: Mapping[str, object]) -> Handler[E]:
        """Canonicalise ``raw``, build the inner handler, apply the wrap chain."""
        spec = HandlerSpec.from_wire(raw)
        handler = self._factories.resolve(spec.factory, spec.factory_params)
        for entry in spec.wrap:
            decorator = self._decorators.resolve(entry)
            handler = cast("Handler[E]", decorator(cast("Handler[Event]", handler)))
        return handler
