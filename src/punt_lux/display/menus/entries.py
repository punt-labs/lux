"""The leaf entries a Lux menu is built from: items and separators.

Every entry renders itself, so a menu is a list of objects rather than a block of
render code. Two surfaces that hold the same entry objects therefore show the
same menu and route a click the same way — the entry carries its own action.

``imgui`` is typed ``Any`` throughout: imgui_bundle ships no type stubs, and the
entries only ever call into it, never construct its types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["MenuEntry", "MenuItem", "MenuSeparator"]


@runtime_checkable
class MenuEntry(Protocol):
    """Something that draws itself inside an open menu."""

    def render(self, imgui: Any) -> bool:
        """Render this entry and return whether the user activated it."""
        ...


@final
class MenuItem:
    """One line in a menu: a label, the state it shows, and what a click does."""

    _label: str
    _shortcut: str
    _checked: bool
    _enabled: bool
    _activate: Callable[[], None]
    __slots__ = ("_activate", "_checked", "_enabled", "_label", "_shortcut")

    def __new__(
        cls,
        label: str,
        activate: Callable[[], None],
        *,
        shortcut: str = "",
        checked: bool = False,
        enabled: bool = True,
    ) -> Self:
        self = super().__new__(cls)
        self._label = label
        self._shortcut = shortcut
        self._checked = checked
        self._enabled = enabled
        self._activate = activate
        return self

    @classmethod
    def toggle(cls, label: str, activate: Callable[[], None], *, checked: bool) -> Self:
        """Return an item that carries a check mark while *checked* holds."""
        return cls(label, activate, checked=checked)

    @classmethod
    def inert(cls, label: str, *, shortcut: str = "", enabled: bool = True) -> Self:
        """Return an item whose click does nothing.

        A replicated item without a routable id lands here: it still reads as
        part of the menu, but the display never invents an id to send back.
        """
        return cls(label, cls._nothing, shortcut=shortcut, enabled=enabled)

    @classmethod
    def caption(cls, label: str) -> Self:
        """Return a greyed line the user can read but not click."""
        return cls.inert(label, enabled=False)

    @property
    def label(self) -> str:
        """Return the text this item shows."""
        return self._label

    def render(self, imgui: Any) -> bool:
        """Render the item, running its action when the user clicks it."""
        clicked, _ = imgui.menu_item(
            self._label, self._shortcut, self._checked, self._enabled
        )
        if clicked:
            self._activate()
        return bool(clicked)

    @staticmethod
    def _nothing() -> None:
        """Do nothing — the action of an item that has none."""


@final
class MenuSeparator:
    """A rule between groups of items."""

    __slots__ = ()

    def render(self, imgui: Any) -> bool:
        """Draw the rule. A separator can never be activated."""
        imgui.separator()
        return False
