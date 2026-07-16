"""Import-time cross-checks that keep the ABC-kind registration honest.

Two independent declarations of "which kinds are on the ABC path" must agree
with the registered specs, and any drift is a latent wire bug — so it fails loud
at import instead:

- **Name parity** — the registered kinds must equal the import-light
  ``AbcKindNames`` sets the container gate reads.
- **Capability parity** — every kind declared interactive here must register a
  spec whose built decoder wires handlers, and Button must canonicalize its
  wire sugar. A spec registered without its ``handler_builder`` (or Button
  without its ``pre_decode``) would pass name parity yet silently decode to a
  handler-less element — clicks and edits firing no event. This guard is the
  independent declaration that catches exactly that omission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

from punt_lux.protocol.elements.abc_kind_names import AbcKindNames

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec
    from punt_lux.protocol.elements.abc_registry import AbcElementRegistry

__all__ = ["AbcKindVerifier"]


class AbcKindVerifier:
    """Fail-loud verifier for the default ABC-kind registration.

    ``INTERACTIVE_KINDS`` and ``SUGAR_KINDS`` are declared here, independently of
    the registered specs, so a spec that forgets its capability is caught rather
    than silently trusted.
    """

    __slots__ = ()

    INTERACTIVE_KINDS: ClassVar[frozenset[str]] = frozenset(
        {
            "button",
            "checkbox",
            "input_text",
            "input_number",
            "slider",
            "color_picker",
            "dialog",
            "collapsing_header",
            "tab_bar",
        }
    )
    SUGAR_KINDS: ClassVar[frozenset[str]] = frozenset({"button"})

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @classmethod
    def verify(cls, registry: AbcElementRegistry) -> None:
        """Check name parity and capability parity, raising on any drift."""
        cls._verify_names(registry)
        cls._verify_capabilities(registry)

    @staticmethod
    def _verify_names(registry: AbcElementRegistry) -> None:
        """Fail loud if the registered kinds disagree with ``AbcKindNames``."""
        if registry.all_kinds != AbcKindNames.MIGRATED_ABC_KINDS:
            diff = registry.all_kinds ^ AbcKindNames.MIGRATED_ABC_KINDS
            msg = f"ABC specs and AbcKindNames disagree on migrated kinds: {diff}"
            raise RuntimeError(msg)
        if registry.container_kinds != AbcKindNames.ABC_CONTAINER_KINDS:
            diff = registry.container_kinds ^ AbcKindNames.ABC_CONTAINER_KINDS
            msg = f"ABC specs and AbcKindNames disagree on container kinds: {diff}"
            raise RuntimeError(msg)

    @classmethod
    def _verify_capabilities(cls, registry: AbcElementRegistry) -> None:
        """Fail loud if an interactive kind's spec does not wire its capability."""
        by_kind = {spec.kind: spec for spec in registry.specs}
        cls._require_capability(by_kind, cls.INTERACTIVE_KINDS, "handlers")
        cls._require_capability(by_kind, cls.SUGAR_KINDS, "pre_decode")

    @staticmethod
    def _require_capability(
        by_kind: dict[str, AbcKindSpec], kinds: frozenset[str], capability: str
    ) -> None:
        """Raise unless every kind in ``kinds`` declares ``capability``."""
        for kind in kinds:
            spec = by_kind.get(kind)
            if spec is None or capability not in spec.capabilities:
                msg = (
                    f"kind {kind!r} must decode with the {capability!r} "
                    f"capability but its spec does not wire it"
                )
                raise RuntimeError(msg)
