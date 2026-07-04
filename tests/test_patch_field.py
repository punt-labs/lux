"""Tests for ``PatchField`` — the shared apply_patch boundary coercer.

``PatchField`` replaces the ``_str_or_raise`` / ``_opt_str_or_raise`` /
``_bool_or_raise`` static methods that were copy-pasted into text.py,
button.py, checkbox.py, and dialog.py. The four exemplars now call this
one surface, so the behavior (TypeError on wrong type, named field in the
message) is tested once here.
"""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.patch_field import PatchField


def test_as_str_returns_the_value() -> None:
    assert PatchField("label").as_str("Save") == "Save"


def test_as_str_rejects_non_str_with_named_field() -> None:
    with pytest.raises(TypeError, match=r"label must be str, got int"):
        PatchField("label").as_str(42)


def test_as_optional_str_passes_none_through() -> None:
    assert PatchField("tooltip").as_optional_str(None) is None


def test_as_optional_str_returns_str() -> None:
    assert PatchField("tooltip").as_optional_str("hi") == "hi"


def test_as_optional_str_rejects_non_str() -> None:
    with pytest.raises(TypeError, match=r"tooltip must be str or None, got int"):
        PatchField("tooltip").as_optional_str(7)


def test_as_bool_returns_the_value() -> None:
    assert PatchField("disabled").as_bool(True) is True


def test_as_bool_rejects_non_bool() -> None:
    with pytest.raises(TypeError, match=r"disabled must be bool, got str"):
        PatchField("disabled").as_bool("yes")


def test_as_bool_rejects_int_one() -> None:
    """``1`` is not a bool — the boundary must not silently coerce it."""
    with pytest.raises(TypeError, match=r"value must be bool, got int"):
        PatchField("value").as_bool(1)


def test_the_four_exemplars_no_longer_define_local_coercers() -> None:
    """The static coercers were deleted from every exemplar (no 5th copy).

    Walks each exemplar's AST and asserts it defines no ``_*_or_raise``
    method — the promise that the coercion lives in one shared surface.
    """
    import ast
    from pathlib import Path

    from punt_lux.protocol import elements

    elements_dir = Path(elements.__file__).parent
    for kind in ("text", "button", "checkbox", "dialog"):
        tree = ast.parse((elements_dir / f"{kind}.py").read_text())
        method_names = [
            item.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for item in node.body
            if isinstance(item, ast.FunctionDef)
        ]
        leftover = [n for n in method_names if n.endswith("_or_raise")]
        assert not leftover, f"{kind}.py still defines local coercers: {leftover}"
