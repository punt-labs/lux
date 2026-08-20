"""HttpCall — one REST request bundled: method, path, body, and identity headers.

Bundling the values a transport needs into one object keeps the transport
contract to a single argument and puts the wire-header rule on the data it
belongs to. There are exactly two kinds of call the CLI's client makes, so the
two constructors name them: :meth:`write` carries a serialized body under ``PUT``,
:meth:`read` carries none under ``GET``. Both stamp the caller's identity headers,
and :meth:`wire_headers` adds the JSON content-type only when there is a body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel

__all__ = ["HttpCall"]


@dataclass(frozen=True, slots=True)
class HttpCall:
    """One HTTP request the transport sends: its verb, target, body, and headers."""

    method: str
    path: str
    body: bytes | None
    headers: Mapping[str, str]

    @classmethod
    def write(cls, path: str, body: BaseModel, headers: Mapping[str, str]) -> Self:
        """A ``PUT`` carrying ``body`` serialized to JSON under the caller's headers."""
        return cls("PUT", path, body.model_dump_json().encode(), headers)

    @classmethod
    def post(cls, path: str, body: BaseModel, headers: Mapping[str, str]) -> Self:
        """A ``POST`` carrying ``body`` as JSON — a create that is not a PUT-by-id."""
        return cls("POST", path, body.model_dump_json().encode(), headers)

    @classmethod
    def patch(cls, path: str, body: BaseModel, headers: Mapping[str, str]) -> Self:
        """A ``PATCH`` carrying ``body`` serialized to JSON — a partial update."""
        return cls("PATCH", path, body.model_dump_json().encode(), headers)

    @classmethod
    def delete(cls, path: str, headers: Mapping[str, str]) -> Self:
        """A ``DELETE`` with no body under the caller's headers."""
        return cls("DELETE", path, None, headers)

    @classmethod
    def command(cls, path: str, headers: Mapping[str, str]) -> Self:
        """A ``POST`` with no body — an action on a resource that takes no arguments.

        The target names everything the call needs, so there is nothing to send;
        a body of ``{}`` would only invite a schema to grow where none belongs.
        """
        return cls("POST", path, None, headers)

    @classmethod
    def read(cls, path: str, headers: Mapping[str, str]) -> Self:
        """A ``GET`` with no body under the caller's headers."""
        return cls("GET", path, None, headers)

    def wire_headers(self) -> dict[str, str]:
        """The headers to send: the caller's identity, plus a content-type for a body.

        A body means a JSON request model, so the content-type is added exactly when
        one is present; a bodiless read carries only the identity headers.
        """
        wire = dict(self.headers)
        if self.body is not None:
            wire["Content-Type"] = "application/json"
        return wire
