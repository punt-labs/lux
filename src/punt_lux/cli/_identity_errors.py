"""Render a :class:`ClientIdentity` validation failure as a usage message.

Split out of ``_shared.py`` (PY-OO-2, module-size target) -- this is the one
concern in that module with no shared vocabulary with the rest of the file's
flag/context plumbing: given a pydantic :class:`~pydantic.ValidationError`,
produce the one-line usage message ``identity_from_flags`` reports to the
caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import ValidationError

__all__ = ["describe_identity_error"]

_IDENTITY_FLAG_BY_FIELD = {
    "kind": "--kind",
    "name": "--name",
    "repo": "--repo",
    "agent": "--agent",
    "lease_ttl": "--as",
}


def describe_identity_error(exc: ValidationError) -> str:
    """Render a :class:`ValidationError` as one line naming the bad flag(s).

    ``ClientIdentity`` is built from resolved values with no per-flag
    provenance, so this maps the model's field name back to the flag a
    caller typed -- ``--kind bogus`` is a cleaner usage message than a raw
    pydantic traceback naming ``kind``.
    """
    parts: list[str] = []
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else "identity"
        flag = _IDENTITY_FLAG_BY_FIELD.get(field, f"--{field}")
        parts.append(f"{flag}: {error['msg']}")
    return "; ".join(parts)
