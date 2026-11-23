"""Public operation request and result contracts."""

from __future__ import annotations

from punt_lux.wire.model.scope import Scope
from punt_lux.wire.operations.common import OpError, OpErrorCode
from punt_lux.wire.operations.config import DisplayModeRequest, DisplayModeState
from punt_lux.wire.operations.dashboard import RenderDashboardRequest
from punt_lux.wire.operations.display_frames import FrameState, FrameStates
from punt_lux.wire.operations.display_info import DisplayInfo
from punt_lux.wire.operations.display_probe import Pong, Screenshot
from punt_lux.wire.operations.display_state import DisplayStateSnapshot
from punt_lux.wire.operations.display_write import FrameStatePatch
from punt_lux.wire.operations.identity import Identified
from punt_lux.wire.operations.inspect_scope import InspectScope
from punt_lux.wire.operations.menu_results import MenuList, Ok, SetMenuRequest
from punt_lux.wire.operations.patches import UpdateRequest
from punt_lux.wire.operations.pubsub import BusEvent, PublishRequest, Received
from punt_lux.wire.operations.pubsub_acks import (
    Published,
    Subscribed,
    Unsubscribed,
)
from punt_lux.wire.operations.query_clients import ClientList
from punt_lux.wire.operations.query_errors import RecentErrors
from punt_lux.wire.operations.query_events import RecentEvents
from punt_lux.wire.operations.query_inspection import SceneInspection
from punt_lux.wire.operations.query_scenes import SceneList
from punt_lux.wire.operations.render import FrameFlags, FrameSpec, RenderRequest
from punt_lux.wire.operations.scene_results import Cleared, SceneShown
from punt_lux.wire.operations.table import RenderTableRequest
from punt_lux.wire.operations.theme import ThemeName, ThemeState
from punt_lux.wire.operations.window import WindowSettings

__all__ = [
    "BusEvent",
    "Cleared",
    "ClientList",
    "DisplayInfo",
    "DisplayModeRequest",
    "DisplayModeState",
    "DisplayStateSnapshot",
    "FrameFlags",
    "FrameSpec",
    "FrameState",
    "FrameStatePatch",
    "FrameStates",
    "Identified",
    "InspectScope",
    "MenuList",
    "Ok",
    "OpError",
    "OpErrorCode",
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
