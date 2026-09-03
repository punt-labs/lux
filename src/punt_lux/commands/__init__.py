"""Humble Object commands: one @final callable class per op, one shared singleton."""

from __future__ import annotations

from punt_lux.commands._ports import (
    CallbackPendingOps,
    CallbackRegisterOps,
    Ctx,
    DisplayInfoOps,
    DisplayModeOps,
    ErrorOps,
    EventOps,
    FrameOps,
    MenuOps,
    PingOps,
    SceneOps,
    ScreenshotOps,
    SessionOps,
    ThemeOps,
    TopicOps,
    WindowOps,
)
from punt_lux.commands._result import CommandResult
from punt_lux.commands.callback_pending import callback_pending
from punt_lux.commands.callback_register import callback_register
from punt_lux.commands.display_get_theme import display_get_theme
from punt_lux.commands.display_info import display_info
from punt_lux.commands.display_mode_get import display_mode_get
from punt_lux.commands.display_screenshot import display_screenshot
from punt_lux.commands.display_window_get import display_window_get
from punt_lux.commands.error_ls import error_ls
from punt_lux.commands.event_ls import event_ls
from punt_lux.commands.frame_close import frame_close
from punt_lux.commands.menu_ls import menu_ls
from punt_lux.commands.menu_set import menu_set
from punt_lux.commands.ping import ping
from punt_lux.commands.scene_clear import scene_clear
from punt_lux.commands.scene_clear_all import scene_clear_all
from punt_lux.commands.scene_dashboard import scene_dashboard
from punt_lux.commands.scene_inspect import scene_inspect
from punt_lux.commands.scene_ls import scene_ls
from punt_lux.commands.scene_show import scene_show
from punt_lux.commands.scene_table import scene_table
from punt_lux.commands.scene_update import scene_update
from punt_lux.commands.session_identify import session_identify
from punt_lux.commands.session_ls import session_ls
from punt_lux.commands.topic_publish import topic_publish
from punt_lux.commands.topic_recv import topic_recv
from punt_lux.commands.topic_subscribe import topic_subscribe
from punt_lux.commands.topic_unsubscribe import topic_unsubscribe

__all__ = [
    "CallbackPendingOps",
    "CallbackRegisterOps",
    "CommandResult",
    "Ctx",
    "DisplayInfoOps",
    "DisplayModeOps",
    "ErrorOps",
    "EventOps",
    "FrameOps",
    "MenuOps",
    "PingOps",
    "SceneOps",
    "ScreenshotOps",
    "SessionOps",
    "ThemeOps",
    "TopicOps",
    "WindowOps",
    "callback_pending",
    "callback_register",
    "display_get_theme",
    "display_info",
    "display_mode_get",
    "display_screenshot",
    "display_window_get",
    "error_ls",
    "event_ls",
    "frame_close",
    "menu_ls",
    "menu_set",
    "ping",
    "scene_clear",
    "scene_clear_all",
    "scene_dashboard",
    "scene_inspect",
    "scene_ls",
    "scene_show",
    "scene_table",
    "scene_update",
    "session_identify",
    "session_ls",
    "topic_publish",
    "topic_recv",
    "topic_subscribe",
    "topic_unsubscribe",
]
