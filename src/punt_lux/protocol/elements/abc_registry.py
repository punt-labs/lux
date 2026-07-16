"""``AbcElementRegistry`` — the single source of truth for migrated ABC kinds.

Every consumer that once hand-copied "which kinds are on the ABC path" reads it
from here instead: the factory builds its per-kind decoders from
``build_decoders``, the encoder factory dispatches from ``encoder_dispatch``,
and the aggregator's isinstance guards read ``abc_types``. Adding a kind adds
one spec to the registration table — no consumer changes.

The registry holds element classes (via each spec), so it participates in the
element import graph. The import-light kind *names* live separately in
``AbcKindNames``; the two are reconciled by a fail-loud cross-check when the
default registry is built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import (
        AbcKindSpec,
        KindDecoder,
        KindEncoder,
        TierBinding,
    )

__all__ = ["AbcElementRegistry"]


class AbcElementRegistry:
    """Maps each migrated wire ``kind`` to its ``AbcKindSpec``.

    Instance-based so the default production registry and any test registry are
    independent. A kind registers exactly once; a duplicate raises ``ValueError``.
    """

    _specs: dict[str, AbcKindSpec]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._specs = {}
        return self

    def register(self, spec: AbcKindSpec) -> None:
        """Register one kind's spec; raise on a duplicate ``kind``."""
        if spec.kind in self._specs:
            msg = f"Duplicate ABC kind registration: {spec.kind!r}"
            raise ValueError(msg)
        self._specs[spec.kind] = spec

    @property
    def all_kinds(self) -> frozenset[str]:
        """Return every registered wire ``kind``."""
        return frozenset(self._specs)

    @property
    def leaf_kinds(self) -> frozenset[str]:
        """Return the kinds decoded on the leaf path (no child recursion)."""
        return frozenset(k for k, s in self._specs.items() if not s.is_container)

    @property
    def container_kinds(self) -> frozenset[str]:
        """Return the conditionally-ABC container kinds."""
        return frozenset(k for k, s in self._specs.items() if s.is_container)

    @property
    def abc_types(self) -> tuple[type, ...]:
        """Return every migrated element class, for isinstance dispatch."""
        return tuple(s.element_type for s in self._specs.values())

    def build_decoders(self, binding: TierBinding) -> dict[str, KindDecoder]:
        """Build every kind's decoder bound to ``binding``'s tier DI."""
        return {k: s.build_decoder(binding) for k, s in self._specs.items()}

    def encoder_dispatch(self) -> tuple[tuple[type, KindEncoder], ...]:
        """Return (element class, encoder) pairs for outbound isinstance dispatch."""
        return tuple((s.element_type, s.encode) for s in self._specs.values())
