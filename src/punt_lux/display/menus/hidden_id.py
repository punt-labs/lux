"""The one ImGui menu-id grammar: compose a guarded ``label##salt``.

ImGui separates a widget's visible label from its hidden id with ``##``, and a
``###`` resets the id -- so a raw ``#`` in a label or in any salt component can
forge that syntax and collide two ids. This type owns the single guard, a
zero-width space after every ``#``, so no menu-identity salt site writes the
escape itself: :meth:`compose` builds a guarded id from a visible label and its
salt. The whb9 lesson is why the guard lives in one place -- guard the *whole*
constructed id, prefix and suffix, not just the visible label -- and it can only
be written once if there is one place to write it.
"""

from __future__ import annotations

from typing import ClassVar, final

__all__ = ["MenuHiddenId"]


@final
class MenuHiddenId:
    """The guarded ImGui id grammar shared by every menu-identity salt site."""

    # ImGui's separator between a widget's visible label and its hidden id.
    _SALT: ClassVar[str] = "##"
    # A zero-width space; placed after each ``#`` so a component's ``#`` cannot
    # forge the ``##``/``###`` heading syntax ImGui parses.
    _ZWSP: ClassVar[str] = chr(0x200B)

    __slots__ = ()

    @classmethod
    def compose(cls, label: str, *salt: str) -> str:
        """Compose a guarded id: ``label##salt`` with every ``#`` neutralised.

        Every component -- the visible label AND each ``:``-joined salt part (hub
        token, owner, item or frame id) -- is guarded, so a ``#`` anywhere cannot
        forge the id syntax and collide two lines that read the same.
        """
        guarded = [cls._guard(component) for component in (label, *salt)]
        return f"{guarded[0]}{cls._SALT}{':'.join(guarded[1:])}"

    @classmethod
    def _guard(cls, component: str) -> str:
        """Neutralise every ``#`` in one component so it cannot forge the salt."""
        return component.replace("#", f"#{cls._ZWSP}")
