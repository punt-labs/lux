"""The replicated menu tree, checked where it arrives.

The socket is a boundary: a Hub-sent payload is not a menu until it has
passed here, rejected whole and named if malformed, so nothing downstream
re-checks a field. Accepted shapes match the Hub's own: a menu of entries,
an action carrying the id a click routes to, and the ``"---"`` separator;
an id-less entry that isn't that separator is malformed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.menus.menu_click import ClickTarget
from punt_lux.display.menus.wire_field import WireField

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "SEPARATOR_LABEL",
    "WireAction",
    "WireEntry",
    "WireLine",
    "WireLineAt",
    "WireMenu",
    "WireSeparator",
]

# A line of a menu: something to read, and at most something to click.
type WireLine = WireAction | WireSeparator
# An entry under a menu: a nested menu, or one of its lines.
type WireEntry = WireMenu | WireLine
# The path to one line, outermost menu first, and the line itself.
type WireLineAt = tuple[tuple[str, ...], WireLine]

# The label that stands in for a separator in an untyped menu payload.
SEPARATOR_LABEL = "---"

# The key that makes an entry a nested menu rather than a line.
_ITEMS = "items"


def _hidden_id(label: str, *salt: str) -> str:
    """Compose an ImGui hidden id from a visible label and its salt components.

    Every component — the visible label AND each ``:``-joined salt part (hub
    token, owner, item id) — is guarded with a zero-width space after each ``#``
    so a ``#`` in *any* of them cannot forge the ``##``/``###`` heading syntax
    ImGui parses (a ``###`` resets the id and collides). The whb9 lesson: guard
    the whole constructed id, prefix and suffix, not just the visible label.
    """
    zero_width = "#" + chr(0x200B)
    guarded = [component.replace("#", zero_width) for component in (label, *salt)]
    return f"{guarded[0]}##{':'.join(guarded[1:])}"


@final
class WireSeparator:
    """The rule between groups of entries: a line with nothing to click."""

    __slots__ = ()

    @classmethod
    def of_payload(cls, entry: Mapping[str, object], *, field: WireField) -> Self:
        """Return the separator *entry* describes, or reject an id-less line."""
        label = entry.get("label")
        if label != SEPARATOR_LABEL:
            raise field.at("label").rejected(
                f"{SEPARATOR_LABEL!r} — an entry with no id is the separator", label
            )
        return cls()

    @property
    def label(self) -> str:
        """Return the text this line reads."""
        return SEPARATOR_LABEL

    @property
    def item_id(self) -> str:
        """Return the id a click routes to — a separator routes nowhere."""
        return ""

    def lines(self, path: tuple[str, ...]) -> Iterator[WireLineAt]:
        """Yield this line and the menus it sits under."""
        yield path, self


@final
class WireAction:
    """One clickable line: what it reads, what it clicks to, and how it shows."""

    _label: str
    _item_id: str
    _shortcut: str
    _enabled: bool
    _frame_id: str | None
    __slots__ = ("_enabled", "_frame_id", "_item_id", "_label", "_shortcut")

    def __new__(
        cls,
        label: str,
        item_id: str,
        *,
        shortcut: str = "",
        enabled: bool = True,
        frame_id: str | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._label = label
        self._item_id = item_id
        self._shortcut = shortcut
        self._enabled = enabled
        self._frame_id = frame_id
        return self

    @classmethod
    def of_payload(cls, entry: Mapping[str, object], *, field: WireField) -> Self:
        """Return the action *entry* describes, rejecting any malformed field."""
        return cls(
            field.at("label").text(entry.get("label")),
            field.at("id").text(entry.get("id")),
            shortcut=field.at("shortcut").optional_text(entry.get("shortcut"), ""),
            enabled=field.at("enabled").flag(entry.get("enabled"), default=True),
            frame_id=field.at("frame_id").optional_text_or_none(entry.get("frame_id")),
        )

    @property
    def label(self) -> str:
        """Return the text this line reads."""
        return self._label

    @property
    def item_id(self) -> str:
        """Return the id a click on this line routes to."""
        return self._item_id

    @property
    def shortcut(self) -> str:
        """Return the accelerator shown beside the label, empty when there is none."""
        return self._shortcut

    @property
    def enabled(self) -> bool:
        """Return whether the user may activate this line."""
        return self._enabled

    @property
    def frame_id(self) -> str | None:
        """Return the frame this action owns, or ``None`` if it owns none."""
        return self._frame_id

    def imgui_label(self, hub_token: str) -> str:
        """Return the display's hidden ImGui id for this clickable line.

        The visible label is salted with ``(hub, item id)`` so two lines that
        read the same never collide; :func:`_hidden_id` guards every component so
        a ``#`` in the label, hub token, or id cannot forge the id syntax. This
        derivation reads the line's own label and id, so it belongs on the line.
        """
        return _hidden_id(self._label, hub_token, self._item_id)

    def click_target(self, menu_label: str) -> ClickTarget:
        """Return what a click on this line reports, under the menu ``menu_label``.

        Bundles the line's own label, id, and frame with its parent menu's label
        — the click identity is the line's own data, so composing it belongs on
        the line rather than on the decoder that reaches into three fields for it.
        """
        return ClickTarget(menu_label, self._label, self._item_id, self._frame_id)

    def lines(self, path: tuple[str, ...]) -> Iterator[WireLineAt]:
        """Yield this line and the menus it sits under."""
        yield path, self


@final
class WireMenu:
    """A replicated menu: its label, and the entries the Hub sent under it."""

    _label: str
    _owner: str
    _entries: tuple[WireEntry, ...]
    __slots__ = ("_entries", "_label", "_owner")

    def __new__(cls, label: str, entries: Sequence[WireEntry], owner: str = "") -> Self:
        self = super().__new__(cls)
        self._label = label
        self._owner = owner
        self._entries = tuple(entries)
        return self

    @classmethod
    def accepted(cls, payloads: Sequence[object], *, origin: str) -> tuple[Self, ...]:
        """Return the menus of *payloads* that are well-formed, logging the rest.

        Rejection is per menu: one malformed payload costs its own menu, not
        the whole bar. *origin* names where the menus arrived, so the logged
        rejection locates the menu as well as the field.
        """
        menus: list[Self] = []
        for index, payload in enumerate(payloads):
            field = WireField(origin).at(index)
            try:
                menus.append(cls.of_payload(payload, field=field))
            except ValueError as exc:
                logger.error("Rejected a replicated menu: %s", exc)
        return tuple(menus)

    @classmethod
    def of_payload(cls, payload: object, *, field: WireField) -> Self:
        """Return the menu *payload* describes, or reject it by field name.

        A missing ``items`` key reads as no entries; a present one must be a
        list of nested menus, actions, or separators.
        """
        menu = field.mapping(payload)
        items = field.at(_ITEMS).sequence(menu.get(_ITEMS, ()))
        raw_owner = menu.get("owner")
        owner = raw_owner if isinstance(raw_owner, str) else ""
        return cls(
            field.at("label").text(menu.get("label")),
            [
                cls._entry_of(item, field=field.at(_ITEMS).at(index))
                for index, item in enumerate(items)
            ],
            owner,
        )

    @property
    def label(self) -> str:
        """Return the title this menu shows."""
        return self._label

    @property
    def entries(self) -> tuple[WireEntry, ...]:
        """Return the entries under this menu, in the order the Hub sent them."""
        return self._entries

    def imgui_label(self, hub_token: str) -> str:
        """Return the display's hidden ImGui id for this menu heading.

        The visible label is salted with ``(hub, owner, label)`` so neither two
        Hubs' nor two sessions' same-named headings collide: the owner segment
        separates same-labelled menus from different agent sessions aggregated
        onto one Hub bar. :func:`_hidden_id` guards every component — label, hub
        token, AND owner — so a ``#`` in any of them cannot forge the id syntax.
        This derivation reads the menu's own label and owner, so it belongs on
        the menu, not its renderer.
        """
        return _hidden_id(self._label, hub_token, self._owner, self._label)

    def lines(self, path: tuple[str, ...] = ()) -> Iterator[WireLineAt]:
        """Yield every line under this menu, each with the menus it sits under."""
        here = (*path, self._label)
        for entry in self._entries:
            yield from entry.lines(here)

    @classmethod
    def _entry_of(cls, item: object, *, field: WireField) -> WireEntry:
        """Return the entry *item* describes: a nested menu, an action, or a rule.

        An entry carrying its own ``items`` is a menu (how the Hub nests a
        client under ``Clients``); one carrying an id is an action; else it
        must be the separator.
        """
        entry = field.mapping(item)
        if _ITEMS in entry:
            return cls.of_payload(entry, field=field)
        if entry.get("id") is None:
            return WireSeparator.of_payload(entry, field=field)
        return WireAction.of_payload(entry, field=field)
