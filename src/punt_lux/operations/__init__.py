"""The operations layer — the single home of every capability's logic.

Each capability is one typed operation on a concern class; :class:`Operations`
composes those classes so one caller has one object to call. This package
re-exports the facade, scope, ports, and the models a surface needs to build a call.
"""

from __future__ import annotations

from punt_lux.operations.facade import Operations
from punt_lux.operations.models import (
    Cleared,
    DisplayModeRequest,
    DisplayModeState,
    OpError,
    Published,
    PublishRequest,
    Received,
    RenderDashboardRequest,
    RenderRequest,
    RenderTableRequest,
    SceneShown,
    Subscribed,
    Unsubscribed,
    UpdateRequest,
)
from punt_lux.operations.models.display_frames import FrameState, FrameStates
from punt_lux.operations.models.display_info import DisplayInfo
from punt_lux.operations.models.display_probe import Pong, Screenshot
from punt_lux.operations.models.display_write import FrameStatePatch
from punt_lux.operations.models.identity import Identified
from punt_lux.operations.models.inspect_scope import InspectScope
from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest
from punt_lux.operations.models.query_clients import ClientList
from punt_lux.operations.models.query_errors import RecentErrors
from punt_lux.operations.models.query_events import RecentEvents
from punt_lux.operations.models.query_inspection import SceneInspection
from punt_lux.operations.models.query_scenes import SceneList
from punt_lux.operations.models.theme import ThemeName, ThemeState
from punt_lux.operations.models.window import WindowSettings
from punt_lux.operations.ports import HubPorts
from punt_lux.operations.scope import Scope

__all__ = [
    "Cleared",
    "ClientList",
    "DisplayInfo",
    "DisplayModeRequest",
    "DisplayModeState",
    "FrameState",
    "FrameStatePatch",
    "FrameStates",
    "HubPorts",
    "Identified",
    "InspectScope",
    "MenuList",
    "Ok",
    "OpError",
    "Operations",
    "Pong",
    "PublishRequest",
    "Published",
    "Received",
    "RecentErrors",
    "RecentEvents",
    "RenderDashboardRequest",
    "RenderRequest",
    "RenderTableRequest",
    "SceneInspection",
    "SceneList",
    "SceneShown",
    "Scope",
    "Screenshot",
    "SetMenuRequest",
    "Subscribed",
    "ThemeName",
    "ThemeState",
    "Unsubscribed",
    "UpdateRequest",
    "WindowSettings",
]
