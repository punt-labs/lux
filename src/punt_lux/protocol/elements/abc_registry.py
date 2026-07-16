"""``AbcElementRegistry`` — the authoritative store of migrated ABC kinds.

Consumers read the kind set here (``build_decoders``, ``encoder_dispatch``,
``abc_types``) instead of hand-copying it; ``AbcKindVerifier`` reconciles it with
the import-light ``AbcKindNames`` the container gate reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import (
        KindDecoder,
        KindEncoder,
        TierBinding,
    )

__all__ = ["AbcElementRegistry"]


class AbcElementRegistry:
    """Maps each migrated wire ``kind`` to its ``AbcKindSpec`` (instance-based)."""

    _specs: dict[str, AbcKindSpec]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._specs = {}
        return self

    def register(self, spec: object) -> None:
        """Register one kind's spec; reject a non-spec or duplicate ``kind``."""
        # ``spec`` is typed ``object`` so this is the validated boundary
        # (PY-EH-1): the ``runtime_checkable`` isinstance is the load-bearing
        # gate a hand-built malformed spec fails on, not a redundant static check.
        if not isinstance(spec, AbcKindSpec):
            raise TypeError(f"not an AbcKindSpec: {spec!r}")
        if spec.kind in self._specs:
            raise ValueError(f"Duplicate ABC kind registration: {spec.kind!r}")
        self._specs[spec.kind] = spec

    @property
    def specs(self) -> tuple[AbcKindSpec, ...]:
        """Return the registered specs, for verification and introspection."""
        return tuple(self._specs.values())

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
