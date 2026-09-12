"""``MenuHiddenId`` -- the one guarded ImGui menu-id compose grammar.

The end-to-end whb9 fidelity controls live in ``test_menu_identity.py``, driving
the real render path; these unit-test the grammar directly: the ``label##salt``
shape, the ``:``-joined salt, and the zero-width guard that keeps a ``#`` in any
component from forging the ``##``/``###`` heading syntax.
"""

from __future__ import annotations

from punt_lux.display.menus.hidden_id import MenuHiddenId

_ZWSP = chr(0x200B)


def test_plain_components_compose_label_hashhash_salt() -> None:
    assert MenuHiddenId.compose("Vox", "pembroke", "music") == "Vox##pembroke:music"


def test_no_salt_yields_an_empty_suffix() -> None:
    assert MenuHiddenId.compose("Vox") == "Vox##"


def test_a_hash_in_the_label_is_guarded_but_stays_visible() -> None:
    composed = MenuHiddenId.compose("a#b", "s")

    # A ZWSP follows the label's '#', so it cannot open the '##' salt early ...
    assert composed == f"a#{_ZWSP}b##s"
    # ... yet the visible text (before the real '##', guards stripped) is intact.
    assert composed.split("##", 1)[0].replace(_ZWSP, "") == "a#b"


def test_a_hashhashhash_in_a_salt_component_cannot_reset_the_id() -> None:
    # ImGui's '###' resets the id to the text after it; guarding every '#' keeps
    # the composed id from collapsing to its tail, so two Hubs stay distinct.
    a = MenuHiddenId.compose("Tools", "pembroke", "a###b")
    b = MenuHiddenId.compose("Tools", "okinos", "a###b")

    assert _ZWSP in a  # the salt's hashes are neutralised
    assert "###" not in a.split("##", 1)[1]  # no raw '###' survives in the suffix
    assert a != b  # the hub token is not dropped, so the ids differ


def test_salt_components_join_on_colon_in_order() -> None:
    assert MenuHiddenId.compose("x", "one", "two", "three") == "x##one:two:three"
