"""The typed REST surface — a thin client of the operations facade.

luxd mounts this surface on its FastAPI app. Every route binds a request model,
calls one operation, and maps the discriminated result to HTTP through one shared
table. The routes translate; the engine decides.

A rejected request produces one of two 422 bodies, by which layer caught it.
FastAPI's request binding rejects a malformed body or query before the operation
runs, with the standard ``detail`` **list** of ``{loc, msg, type}`` objects that
names the offending field. A semantic ``invalid_request`` the operation itself
returns (a repo that is not an existing directory, a value it range-checks)
becomes a ``detail`` **string** carrying the reason. Both are 422; the list form
is FastAPI's, the string form is the operation's — see ``HttpErrorMap.respond``.
"""

from __future__ import annotations

from punt_lux.rest.app import DEFAULT_SCOPE, HubHealth, RestSurface

__all__ = ["DEFAULT_SCOPE", "HubHealth", "RestSurface"]
