"""Import-time cross-checks that keep the ABC-kind registration honest.

Two independent declarations of "which kinds are on the ABC path" must agree with
the registered specs — drift is a latent wire bug, so it fails loud at import:

- **Name parity** — the registered kinds equal the import-light ``AbcKindNames``
  sets the container gate reads.
- **Capability parity** — every interactive kind registers a handler-wired spec,
  and Button canonicalizes its sugar. A spec missing that wiring passes name
  parity yet silently decodes handler-less; this guard catches the omission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

from punt_lux.protocol.elements.abc_capability import Capability
from punt_lux.protocol.elements.abc_kind_names import AbcKindNames

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec
    from punt_lux.protocol.elements.abc_registry import AbcElementRegistry

__all__ = ["AbcKindVerifier"]


class AbcKindVerifier:
    """Fail-loud verifier for the default ABC-kind registration.

    ``INTERACTIVE_KINDS`` and ``SUGAR_KINDS`` are declared here, independently of
    the registered specs, so a spec that forgets its capability is caught rather
    than silently trusted. Migrating a NEW interactive kind means adding it to
    ``INTERACTIVE_KINDS`` (alongside the table and ``AbcKindNames``): this set is
    the hand-maintained witness that gives the capability check its teeth —
    omitting it lets a new interactive kind ship handler-less.
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
            "combo",
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
        cls._require_capability(by_kind, cls.INTERACTIVE_KINDS, Capability.HANDLERS)
        cls._require_capability(by_kind, cls.SUGAR_KINDS, Capability.PRE_DECODE)

    @staticmethod
    def _require_capability(
        by_kind: dict[str, AbcKindSpec], kinds: frozenset[str], capability: Capability
    ) -> None:
        """Raise unless every kind in ``kinds`` declares ``capability``."""
        for kind in kinds:
            spec = by_kind.get(kind)
            if spec is None or capability not in spec.capabilities:
                msg = (
                    f"kind {kind!r} must decode with the {capability.value!r} "
                    f"capability but its spec does not wire it"
                )
                raise RuntimeError(msg)
