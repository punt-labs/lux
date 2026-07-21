"""The display-mode request and state for a caller's project config."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from punt_lux.operations.models.common import OpError

__all__ = ["DisplayModeRequest", "DisplayModeState"]


class DisplayModeRequest(BaseModel):
    """A display-mode write: the mode to set and the project it applies to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["on", "off"]
    repo: str  # absolute path to the caller's project

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, value: str) -> str:
        # REST binds this model directly, so the one repo rule must run here as
        # well as in parse — a bad repo is then a bound-time 422, not a 500 in
        # the config writer. check_repo is the shared rule the read path uses.
        if (error := cls.check_repo(value)) is not None:
            raise ValueError(error.reason)
        return value

    @classmethod
    def parse(cls, mode: str, repo: str) -> DisplayModeRequest | OpError:
        """Map the ``y``/``n`` toggle to a request, or an ``OpError``; never raises."""
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

    @classmethod
    def check_repo(cls, repo: str) -> OpError | None:
        """Return an ``OpError`` for a bad repo, or ``None`` when it is a project.

        luxd's cwd is not the agent's project, so a caller must name its project
        by absolute path to an existing directory; ``None`` is the "valid" answer.
        """
        if not repo:
            return cls._invalid("repo is required and must be a non-empty string")
        path = Path(repo)
        if not path.is_absolute():
            return cls._invalid(f"repo must be an absolute path; got {repo!r}")
        if not path.exists():
            return cls._invalid(f"repo path does not exist: {repo}")
        if not path.is_dir():
            return cls._invalid(f"repo must be a directory; got {repo}")
        return None

    @staticmethod
    def _invalid(reason: str) -> OpError:
        """Build the ``invalid_request`` this model reports for a malformed repo."""
        return OpError(code="invalid_request", reason=reason)


class DisplayModeState(BaseModel):
    """The display mode a project's config currently records."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    mode: Literal["on", "off"]

    @classmethod
    def from_config(cls, display: str) -> DisplayModeState:
        """Map the stored ``y``/``n`` field to the on/off state."""
        return cls(mode="on" if display == "y" else "off")
