"""Loud ``PublishSink`` for module-level / standalone-decoder decode paths.

When an Element is decoded outside a real tier (the legacy
``element_from_dict`` agent path, ``ButtonElement.from_dict`` or
``DialogElement.from_dict`` called ad-hoc from tests) there is no Hub
wired to receive ``publish`` decorator fan-out. The decoders still
demand a ``PublishSink`` — silently dropping the publish path is
banned. ``RaisingPublishSink`` is the boundary safety net: explicit to
construct, loud to call. A decode-then-click flow that reaches this
sink surfaces the missing Hub wiring as a ``RuntimeError`` instead of
swallowing the message.

Tier code (luxd hub, MCP server) constructs its own ``JsonElementFactory``
with the Hub-bound sink; this class is only the no-tier fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

__all__ = ["RaisingPublishSink"]


class RaisingPublishSink:
    """Explicit-to-construct, loud-to-call ``PublishSink`` for no-tier decode.

    Satisfies the ``PublishSink`` Protocol structurally without
    inheriting from it — the Protocol lives in ``domain.handlers``
    (inner layer), this sink lives in ``protocol`` (outer layer). The
    structural match is enough; cast at the call site documents the
    seam.
    """

    __slots__ = ("_origin",)

    _origin: str

    def __new__(cls, origin: str) -> Self:
        self = super().__new__(cls)
        self._origin = origin
        return self

    def __call__(self, topic: str, _payload: Mapping[str, object]) -> None:
        msg = (
            f"{self._origin} path published to topic={topic!r} without a real "
            "PublishSink wired; construct the decoder/factory with the "
            "Hub-bound publish_sink at the tier boundary instead"
        )
        raise RuntimeError(msg)
