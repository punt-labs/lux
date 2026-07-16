"""Button wire-sugar canonicalization — promote ``click``/``publish`` to handlers.

A Button may be written on the wire with top-level ``click`` and ``publish``
sugar instead of a full ``handlers`` list. Canonicalization is a pure wire-dict
transform with no dependency on the element classes, so it lives in its own
import-light module: the factory's registered Button decoder applies it before
decode, and the Dialog codec applies it to each child Button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

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
        """Promote top-level ``click`` and ``publish`` sugar to ``handlers``.

        Wire sugar examples:
          ``{"click": "confirm", "publish": ["topic"]}``
          ``{"publish": ["topic"]}``  (no click verb → noop factory)
          ``{"click": "cancel"}``     (no publish → no decorator)

        If the raw dict already has a ``handlers`` key, returns unchanged.
        Idempotent — a second pass finds ``handlers`` present and no-ops.
        """
        click = raw.get("click")
        publish = raw.get("publish")
        if click is None and publish is None:
            return raw
        if "handlers" in raw:
            return raw
        factory = "call_model" if click else "noop"
        params: dict[str, object] = {}
        if click:
            params["verb"] = click
        wrap: list[dict[str, object]] = []
        if publish:
            wrap.append({"decorator": "publish", "topics": publish})
        handler_spec: dict[str, object] = {
            "event": "click",
            "factory": factory,
            **params,
            "wrap": wrap,
        }
        merged = dict(raw)
        merged["handlers"] = [handler_spec]
        merged.pop("click", None)
        merged.pop("publish", None)
        return merged
