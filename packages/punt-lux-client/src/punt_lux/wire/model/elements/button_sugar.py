"""Button wire-sugar canonicalization — promote ``click``/``publish`` to handlers.

A Button may be written on the wire with top-level ``click`` and ``publish``
sugar instead of a full ``handlers`` list. Canonicalization is a pure wire-dict
transform with no dependency on the element classes, so it lives in its own
import-light module: the factory's registered Button decoder applies it before
decode, and the Dialog codec applies it to each child Button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["ButtonWireSugar"]


class ButtonWireSugar:
    """Canonicalize a Button wire dict's ``click``/``publish`` sugar."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def canonicalize(raw: Mapping[str, object]) -> Mapping[str, object]:
        """Promote top-level ``click`` and list-``publish`` sugar to ``handlers``.

        Wire sugar examples:
          ``{"click": "confirm", "publish": ["topic"]}``
          ``{"publish": ["topic"]}``  (no click verb → noop factory)
          ``{"click": "cancel"}``     (no publish → no decorator)

        The list form of ``publish`` is the decorator shorthand — a topic list the
        decorator fans the click event to. A *mapping* ``publish`` (``{"topic":
        ..., "payload": ...}``) sends the payload the agent wrote; it is the typed
        publish-on-click attribute the Button codec reads directly, left in place
        here and never promoted to a decorator, so the two forms never collide.

        If the raw dict already has a ``handlers`` key, returns unchanged.
        Idempotent — a second pass finds ``handlers`` present and no-ops.
        """
        click = raw.get("click")
        publish = raw.get("publish")
        decorator_publish = (
            cast("list[object]", publish) if isinstance(publish, list) else None
        )
        if click is None and decorator_publish is None:
            return raw
        if "handlers" in raw:
            return raw
        factory = "call_model" if click else "noop"
        params: dict[str, object] = {}
        if click:
            params["verb"] = click
        wrap: list[dict[str, object]] = []
        if decorator_publish:
            wrap.append({"decorator": "publish", "topics": decorator_publish})
        handler_spec: dict[str, object] = {
            "event": "click",
            "factory": factory,
            **params,
            "wrap": wrap,
        }
        merged = dict(raw)
        merged["handlers"] = [handler_spec]
        merged.pop("click", None)
        # The mapping publish attribute stays; only the list decorator form is
        # consumed into ``handlers`` here.
        if decorator_publish is not None:
            merged.pop("publish", None)
        return merged
