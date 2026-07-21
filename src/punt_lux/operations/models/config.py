"""The display-mode request and state for a caller's project config."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

__all__ = ["DisplayModeRequest", "DisplayModeState"]


class DisplayModeRequest(BaseModel):
    """A display-mode write: the mode to set and the project it applies to."""

    mode: Literal["on", "off"]
    repo: str  # absolute path to the caller's project

    @classmethod
    def from_toggle(cls, mode: str, repo: str) -> DisplayModeRequest:
        """Build from the MCP ``y``/``n`` toggle; raise on an invalid mode."""
        if mode == "y":
            return cls(mode="on", repo=repo)
        if mode == "n":
            return cls(mode="off", repo=repo)
        msg = f"Invalid mode '{mode}'. Use 'y' or 'n'."
        raise ValueError(msg)


class DisplayModeState(BaseModel):
    """The display mode a project's config currently records."""

    kind: Literal["ok"] = "ok"
    mode: Literal["on", "off"]

    @classmethod
    def from_config(cls, display: str) -> DisplayModeState:
        """Map the stored ``y``/``n`` field to the on/off state."""
        return cls(mode="on" if display == "y" else "off")
