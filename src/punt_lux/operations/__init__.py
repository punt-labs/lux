"""The operations layer — the single home of every capability's logic.

Each capability is one typed operation on a concern class. The :class:`Operations`
facade (in :mod:`punt_lux.operations.facade`) composes those classes so one caller
— an MCP adapter, a REST route, or a test — has one object to call. This package
surface re-exports the facade, the caller scope, the injected ports, and the
request and result models a surface needs to build and read a call.
"""

from __future__ import annotations

from punt_lux.domain.hub.menu_models import MenuAction
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
from punt_lux.operations.models.display_info import DisplayInfo
from punt_lux.operations.models.display_probe import Pong, Screenshot
from punt_lux.operations.models.display_write import FrameStatePatch
from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest
from punt_lux.operations.models.query_clients import ClientList
from punt_lux.operations.models.query_errors import RecentErrors
from punt_lux.operations.models.query_events import RecentEvents
from punt_lux.operations.models.query_inspection import (
    MirrorNotRequested,
    MirrorPresent,
    MirrorUnavailable,
    SceneInspection,
)
from punt_lux.operations.models.query_scenes import SceneList
from punt_lux.operations.models.theme import SetThemeRequest, ThemeName, ThemeState
from punt_lux.operations.models.window import WindowSettings, WindowSettingsPatch
from punt_lux.operations.ports import HubPorts
from punt_lux.operations.scope import Scope

__all__ = [
    "Cleared",
    "ClientList",
    "DisplayInfo",
    "DisplayModeRequest",
    "DisplayModeState",
    "FrameStatePatch",
    "HubPorts",
    "MenuAction",
    "MenuList",
    "MirrorNotRequested",
    "MirrorPresent",
    "MirrorUnavailable",
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
    "SetThemeRequest",
    "Subscribed",
    "ThemeName",
    "ThemeState",
    "Unsubscribed",
    "UpdateRequest",
    "WindowSettings",
    "WindowSettingsPatch",
]
