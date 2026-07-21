"""The display-mode request and state for a caller's project config."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from punt_lux.operations.models.common import OpError

__all__ = ["DisplayModeRequest", "DisplayModeState"]


class DisplayModeRequest(BaseModel):
    """A display-mode write: the mode to set and the project it applies to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["on", "off"]
    repo: str  # absolute path to the caller's project

    @classmethod
    def parse(cls, mode: str, repo: str) -> DisplayModeRequest | OpError:
        """Validate the ``y``/``n`` toggle and the repo, never raising.

        The legacy MCP tools raised ``ValueError`` on bad input; that raise is now
        the adapter's job — the operation layer only ever returns a discriminated
        result, so a bad mode or repo becomes an ``invalid_request`` ``OpError``
        the adapter reproduces as the legacy exception.
        """
        if mode == "y":
            resolved: Literal["on", "off"] = "on"
        elif mode == "n":
            resolved = "off"
        else:
            return OpError(
                code="invalid_request", reason=f"Invalid mode '{mode}'. Use 'y' or 'n'."
            )
        repo_error = cls.check_repo(repo)
        if repo_error is not None:
            return repo_error
        return cls(mode=resolved, repo=repo)

    @staticmethod
    def check_repo(repo: str) -> OpError | None:
        """Return an ``OpError`` for a bad repo path, or ``None`` when it is valid.

        The MCP server runs inside luxd, whose cwd is wherever launchd started it
        — never the agent's project. Every caller must name its project with an
        absolute path to an existing directory. ``None`` is the documented
        "no error" contract shared by the read and write operations.
        """
        if not repo:
            return OpError(
                code="invalid_request",
                reason="repo is required and must be a non-empty string",
            )
        path = Path(repo)
        if not path.is_absolute():
            return OpError(
                code="invalid_request",
                reason=f"repo must be an absolute path; got {repo!r}",
            )
        if not path.exists():
            return OpError(
                code="invalid_request", reason=f"repo path does not exist: {repo}"
            )
        if not path.is_dir():
            return OpError(
                code="invalid_request", reason=f"repo must be a directory; got {repo}"
            )
        return None


class DisplayModeState(BaseModel):
    """The display mode a project's config currently records."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    mode: Literal["on", "off"]

    @classmethod
    def from_config(cls, display: str) -> DisplayModeState:
        """Map the stored ``y``/``n`` field to the on/off state."""
        return cls(mode="on" if display == "y" else "off")
