"""Text outbound end-to-end — io-model dispatch from wire dict to ABC-shaped Element.

Per docs/oo-refactor/pr3-v2.1-design.md §7(iii): commit (iii) routes Text
through ``JsonElementFactory`` so ``element_from_dict`` returns an
ABC-shaped ``TextElement`` bound to its tier's renderer factory + emit.
"""

from __future__ import annotations

from punt_lux.domain.element_abc import Element as DomainElement
from punt_lux.protocol.elements import element_from_dict


def test_text_dict_decodes_to_domain_element_abc_subclass() -> None:
    elem = element_from_dict({"kind": "text", "id": "t1", "content": "Hello"})
    assert isinstance(elem, DomainElement)
