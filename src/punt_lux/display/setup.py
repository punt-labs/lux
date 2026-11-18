# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Native window, font and addon setup, separate from render-loop lifecycle."""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

from punt_lux.display.fonts import FontLoader
from punt_lux.display.idle_screen import render_idle
from punt_lux.display.macos import set_regular_activation_policy
from punt_lux.display.markdown_font import MarkdownFont

logger = logging.getLogger(__name__)


class DisplaySetup:
    """Build native startup options; the coordinator only supplies callbacks."""

    @staticmethod
    def parameters() -> Any:
        hello_imgui = import_module("imgui_bundle.hello_imgui")

        params = hello_imgui.RunnerParams()
        params.app_window_params.window_title = "Lux"
        params.app_window_params.window_geometry.size = (1200, 800)
        options = params.imgui_window_params
        options.show_menu_bar = True
        options.show_menu_app = False
        options.show_menu_view = False
        options.show_menu_view_themes = False
        options.show_status_bar = False
        options.show_status_fps = False
        options.remember_status_bar_settings = False
        params.callbacks.load_additional_fonts = FontLoader().load
        params.fps_idling.fps_idle = 30.0
        return params

    @staticmethod
    def addons() -> Any:
        hello_imgui = import_module("imgui_bundle.hello_imgui")
        immapp = import_module("imgui_bundle.immapp")

        addons = immapp.AddOnsParams()
        addons.with_implot = True
        try:
            imgui_md = import_module("imgui_bundle.imgui_md")

            options = imgui_md.MarkdownOptions()
            options.font_options.regular_size = 13.0
            MarkdownFont().apply_to(options, hello_imgui.add_assets_search_path)
            addons.with_markdown_options = options
        except ImportError:
            logger.warning("imgui_md unavailable; markdown renders as plain text")
            addons.with_markdown = True
        return addons

    @staticmethod
    def post_init() -> None:
        imgui = import_module("imgui_bundle.imgui")

        imgui.get_io().config_flags |= imgui.ConfigFlags_.docking_enable.value
        set_regular_activation_policy()

    @staticmethod
    def background(imgui: Any) -> None:
        """Native docking host and ambient background for the current frame."""
        imgui.dock_space_over_viewport(
            flags=imgui.DockNodeFlags_.passthru_central_node.value,
        )
        render_idle(imgui)
