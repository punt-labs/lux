"""Text outbound end-to-end — io-model dispatch from wire dict to ABC-shaped Element.

Per docs/oo-refactor/pr3-v2.1-design.md §7(ii) (RED test) and §7(iii) (the
commit that flips this to GREEN by rewriting TextElement on the ABC and
registering Text through ``JsonElementFactory``).

The test currently xfails: ``protocol.elements.element_from_dict`` still
routes Text through ``_codec`` (the PR-2 dataclass path), so the returned
object is a frozen dataclass — not an io-model ABC subclass and not bound
to a renderer factory or emit channel. Commit (iii) makes it pass.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.element_abc import Element as DomainElement
from punt_lux.protocol.elements import element_from_dict

pytestmark = pytest.mark.xfail(
    reason=(
        "Text dispatch through JsonElementFactory lands in design §7(iii); "
        "this commit (ii) only ships the Element ABC + Renderer Protocols."
    ),
    strict=True,
)


def test_text_dict_decodes_to_domain_element_abc_subclass() -> None:
    elem = element_from_dict({"kind": "text", "id": "t1", "content": "Hello"})
    assert isinstance(elem, DomainElement)
