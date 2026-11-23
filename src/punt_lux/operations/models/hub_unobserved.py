"""Raw Display facts cannot witness the Hub's connection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HubUnobserved(BaseModel, frozen=True):
    """The facts were not captured through a named Hub dial."""

    state: Literal["unobserved"] = "unobserved"
