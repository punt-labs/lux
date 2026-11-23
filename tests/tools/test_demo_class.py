"""DemoClass -- AST-decided interactive / rendering / exempt verdicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.demo_class import DemoClass

ROOT = Path(__file__).resolve().parents[2]
D = "src/punt_lux/display/"


@pytest.fixture
def demo() -> DemoClass:
    return DemoClass(ROOT)


@pytest.mark.parametrize(
    "path",
    [
        D + "render_loop.py",
        D + "dock_pill.py",
        D + "frame_commands.py",
        D + "interaction_delivery.py",
        D + "renderers/button_renderer.py",
        D + "renderers/imgui/dialog.py",
        "src/punt_lux/wire/model/handlers/button_catalog.py",
        "plugin/commands/display.screenshot.md",
    ],
)
def test_input_reading_or_forwarding_files_are_interactive(
    demo: DemoClass, path: str
) -> None:
    assert demo.classify(path).is_interactive


@pytest.mark.parametrize(
    "path",
    [
        D + "renderers/text_renderer.py",
        D + "renderers/image_renderer.py",
        D + "framebuffer_capture.py",
        D + "socket_server.py",
        D + "paint_telemetry.py",
        "src/punt_lux/applets/beads/beads_board.py",
    ],
)
def test_display_only_files_are_not_interactive(demo: DemoClass, path: str) -> None:
    assert not demo.classify(path).is_interactive


def test_beads_board_is_rendering(demo: DemoClass) -> None:
    assert demo.classify("src/punt_lux/applets/beads/beads_board.py").is_rendering


def test_plugin_markdown_is_not_exempt(demo: DemoClass) -> None:
    assert not demo.classify("plugin/commands/display.screenshot.md").is_exempt


@pytest.mark.parametrize(
    "path", ["docs/WORKFLOW.md", "tests/tools/test_demo_class.py", ".oo-baseline.json"]
)
def test_docs_tests_and_baselines_are_exempt(demo: DemoClass, path: str) -> None:
    assert demo.classify(path).kind == "exempt"


@pytest.mark.parametrize(
    "path", [".github/workflows/test.yml", "src/punt_lux/kernel/paths.py"]
)
def test_behavior_files_are_not_exempt(demo: DemoClass, path: str) -> None:
    assert not demo.classify(path).is_exempt


def _display_file(tmp_path: Path, body: str) -> tuple[DemoClass, str]:
    path = tmp_path / "src/punt_lux/display/probe.py"
    path.parent.mkdir(parents=True)
    path.write_text(f"def f(imgui):\n    {body}\n")
    return DemoClass(tmp_path), "src/punt_lux/display/probe.py"


def test_tooltip_hover_is_not_interactive(tmp_path: Path) -> None:
    demo, path = _display_file(
        tmp_path, "return imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value)"
    )
    assert not demo.classify(path).is_interactive


def test_plain_hover_is_interactive(tmp_path: Path) -> None:
    demo, path = _display_file(tmp_path, "return imgui.is_item_hovered()")
    assert demo.classify(path).is_interactive


@pytest.mark.parametrize(
    "body",
    [
        "imgui.begin_child('x')",
        "imgui.begin_table('x', 2)",
        "imgui.invisible_button('x', s)",
    ],
)
def test_containers_and_invisible_buttons_are_not_interactive(
    tmp_path: Path, body: str
) -> None:
    demo, path = _display_file(tmp_path, body)
    assert not demo.classify(path).is_interactive


def test_unparseable_display_file_is_not_waved_through(tmp_path: Path) -> None:
    path = tmp_path / "src/punt_lux/display/bad.py"
    path.parent.mkdir(parents=True)
    path.write_text("def (\n")
    assert DemoClass(tmp_path).classify("src/punt_lux/display/bad.py").is_interactive


def test_summary_reports_pr_level_answers(demo: DemoClass) -> None:
    summary = demo.summarize(["docs/WORKFLOW.md", D + "dock_pill.py"])
    assert "interactive(pr): yes" in summary
    assert "demo_exempt(all): no" in summary


def test_widget_with_discarded_result_is_not_interactive(tmp_path: Path) -> None:
    demo, path = _display_file(tmp_path, "imgui.selectable('x', False)")
    assert not demo.classify(path).is_interactive


def test_widget_with_used_result_is_interactive(tmp_path: Path) -> None:
    demo, path = _display_file(tmp_path, "return imgui.selectable('x', False)")
    assert demo.classify(path).is_interactive
