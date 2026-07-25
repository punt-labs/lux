"""Tests for ``DefaultContainerKinds`` — the container-path spec assembler.

The container builder owns the spec for every conditionally-ABC container kind.
These tests pin that every spec it yields is a container and that the set matches
the import-light name registry, so a newly-migrated container added here (or one
mistakenly dropped) is caught against the single source of truth.
"""

from __future__ import annotations

from punt_lux.protocol.elements.abc_container_kinds import DefaultContainerKinds
from punt_lux.protocol.elements.abc_kind_names import AbcKindNames


class TestDefaultContainerKinds:
    """The container builder yields exactly the conditionally-ABC container kinds."""

    def test_every_spec_is_a_container(self) -> None:
        assert all(spec.is_container for spec in DefaultContainerKinds.specs())

    def test_kinds_are_the_container_kinds(self) -> None:
        kinds = {spec.kind for spec in DefaultContainerKinds.specs()}
        assert kinds == AbcKindNames.ABC_CONTAINER_KINDS

    def test_no_duplicate_kinds(self) -> None:
        specs = DefaultContainerKinds.specs()
        assert len({spec.kind for spec in specs}) == len(specs)
