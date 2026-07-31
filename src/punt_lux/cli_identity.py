"""CliIdentity — the identity a ``lux`` invocation declares, derived from context.

Under the same-user-localhost trust model Lux stores no credential, so a command
needs no enrollment and no session lookup: its identity is a *name*, and the name
falls out of where the command runs. Every run resolves it the same way, in one
order — an explicit override, then the git repository the command sits in, then a
headless fallback — so a command in a repo attributes its UI to that repo without
any stored state, and a command with no repo still owns a real, named scene rather
than the anonymous stand-in the reserved ``"rest"`` connection used to be.
"""

from __future__ import annotations

import os
from typing import final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.repo_root import RepoRoot

__all__ = ["CliIdentity"]

# The name a command outside any repository owns its context-free scenes under —
# real and named, never the old anonymous "rest".
_HEADLESS_NAME = "lux-cli"
# The environment override, the equivalent of the --as flag for a scripted caller.
_OVERRIDE_ENV = "LUX_CLIENT"


@final
class CliIdentity:
    """Resolve a ``lux`` command's declared identity from its working context."""

    __slots__ = ()

    @classmethod
    def resolve(cls, override: str | None = None) -> ClientIdentity:
        """Return the ``cli`` identity this invocation declares.

        The name is the override (``--as`` or ``LUX_CLIENT``) when given, else the
        git repository's directory name, else the headless fallback. The repository
        is always derived from the git root when present, so an overridden *name* in
        a repo still owns that repo; a command outside a repository owns no repo.
        """
        repo = RepoRoot.of(_HEADLESS_NAME)
        return ClientIdentity(
            kind="cli",
            name=cls._override(override) or repo.name,
            repo=repo.declared_path,
        )

    @staticmethod
    def _override(override: str | None) -> str:
        """Return the explicit name to declare, from the flag or the environment."""
        flag = (override or "").strip()
        return flag or os.environ.get(_OVERRIDE_ENV, "").strip()
