"""The default ABC-kind registry — assembled from the leaf and container kinds.

``DefaultAbcKinds.build()`` combines every migrated leaf spec
(:class:`DefaultLeafKinds`) with every migrated container spec
(:class:`DefaultContainerKinds`), registers them into a fresh
``AbcElementRegistry``, and verifies the result with ``AbcKindVerifier`` (name
and capability parity). Migrating a new kind adds one spec to the leaf or
container module plus its string in ``AbcKindNames`` — no other module in the
decode/encode path changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.abc_container_kinds import DefaultContainerKinds
from punt_lux.protocol.elements.abc_kind_verify import AbcKindVerifier
from punt_lux.protocol.elements.abc_leaf_kinds import DefaultLeafKinds
from punt_lux.protocol.elements.abc_registry import AbcElementRegistry

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec

__all__ = ["DEFAULT_ABC_REGISTRY", "DefaultAbcKinds"]


class DefaultAbcKinds:
    """Builds the production ``AbcElementRegistry`` with every migrated kind."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def _leaf_specs() -> list[AbcKindSpec]:
        """Return the leaf-path specs from the leaf-kinds module."""
        return DefaultLeafKinds.specs()

    @staticmethod
    def _container_specs() -> list[AbcKindSpec]:
        """Return the container-path specs from the container-kinds module."""
        return DefaultContainerKinds.specs()

    @classmethod
    def build(cls) -> AbcElementRegistry:
        """Register every migrated leaf and container kind, then verify."""
        registry = AbcElementRegistry()
        for spec in (*cls._leaf_specs(), *cls._container_specs()):
            registry.register(spec)
        AbcKindVerifier.verify(registry)
        return registry


DEFAULT_ABC_REGISTRY: AbcElementRegistry = DefaultAbcKinds.build()
