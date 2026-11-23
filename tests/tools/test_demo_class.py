"""DemoClass -- AST-decided interactive / rendering / exempt verdicts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.demo_class import ChangeSet, DemoClass, GitError, main

ROOT = Path(__file__).resolve().parents[2]
S = "src/punt_lux/"
D = S + "display/"
BY_NAME = "module is named for interactions"

INTERACTIVE_REAL_FILES = [
    (D + "render_loop.py", "calls is_window_hovered()"),
    (D + "dock_pill.py", "calls get_mouse_pos()"),
    (D + "frame_commands.py", BY_NAME),
    (D + "interaction_delivery.py", BY_NAME),
    (D + "renderers/button_renderer.py", "calls button()"),
    (D + "renderers/imgui/dialog.py", "calls begin_popup_modal()"),
    (D + "terminal/keymap.py", "reads io.key_ctrl"),
    (D + "menus/menu_click.py", BY_NAME),
    (S + "applets/serviced_click.py", BY_NAME),
    (S + "applets/leg.py", "calls clicked()"),
    (S + "applets/serviced_click.py", "references event ServicedClick"),
    (S + "pty/viewer_input.py", BY_NAME),
    (S + "pty/control_input.py", BY_NAME),
    (
        S + "wire/model/standalone_input_text_handler.py",
        "references event ValueChanged",
    ),
    (S + "wire/model/interaction.py", "references event ButtonClicked"),
    (S + "wire/model/selection_interaction.py", "references event RowSelectionChanged"),
    (S + "wire/model/standalone_button_handler.py", "references event ButtonClicked"),
    (S + "wire/model/elements/button.py", "references event ButtonClicked"),
    (D + "menus/entries.py", "calls menu_item()"),
    (D + "renderers/imgui/tree.py", "calls tree_node()"),
    (S + "wire/model/handlers/button_catalog.py", "interactive by path"),
    ("plugin/commands/display.screenshot.md", "interactive by path"),
]

DISPLAY_ONLY_REAL_FILES = [
    D + "renderers/text_renderer.py",
    D + "renderers/image_renderer.py",
    D + "renderers/tooltip_painter.py",
    D + "framebuffer_capture.py",
    D + "socket_server.py",
    D + "paint_telemetry.py",
    S + "applets/beads/beads_board.py",
    S + "applets/latency.py",
    S + "applets/__init__.py",
]


@pytest.fixture
def demo() -> DemoClass:
    return DemoClass(ROOT)


@pytest.mark.parametrize(("path", "reason"), INTERACTIVE_REAL_FILES)
def test_input_reading_or_forwarding_files_are_interactive(
    demo: DemoClass, path: str, reason: str
) -> None:
    assert (ROOT / path).is_file()
    assert reason in demo.classify(path).reasons


@pytest.mark.parametrize("path", DISPLAY_ONLY_REAL_FILES)
def test_display_only_files_are_rendering_with_no_reason(
    demo: DemoClass, path: str
) -> None:
    assert (ROOT / path).is_file()
    verdict = demo.classify(path)
    assert (verdict.kind, verdict.reasons) == ("rendering", ())


def test_plugin_markdown_is_not_exempt(demo: DemoClass) -> None:
    assert not demo.classify("plugin/commands/display.screenshot.md").is_exempt


@pytest.mark.parametrize(
    "path",
    [
        "docs/WORKFLOW.md",
        "tests/tools/test_demo_class.py",
        ".oo-baseline.json",
        ".oo-audit.jsonl",
        ".oo-coupling-baseline.json",
        ".oo-coupling-audit.jsonl",
        ".suppression-baseline.json",
        ".suppression-audit.jsonl",
        ".layer-baseline.json",
        ".layer-audit.jsonl",
    ],
)
def test_docs_tests_and_ratchet_files_are_exempt(demo: DemoClass, path: str) -> None:
    assert demo.classify(path).kind == "exempt"


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/test.yml",
        S + "kernel/paths.py",
        "sub/.oo-baseline.json",
        ".oo-baseline.json.bak",
    ],
)
def test_behavior_files_are_not_exempt(demo: DemoClass, path: str) -> None:
    assert not demo.classify(path).is_exempt


def test_exempt_outranks_interactive_and_rendering(demo: DemoClass) -> None:
    assert demo.classify(D + "README.md").kind == "exempt"


def test_interactive_outranks_rendering(demo: DemoClass) -> None:
    assert demo.classify(D + "dock_pill.py").kind == "interactive"


def _src_file(tmp_path: Path, relpath: str, body: str | bytes) -> tuple[DemoClass, str]:
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(f"def f(imgui, io, h, e, clipper):\n    {body}\n")
    return DemoClass(tmp_path), relpath


def _probe(tmp_path: Path, body: str) -> tuple[DemoClass, str]:
    return _src_file(tmp_path, D + "probe.py", body)


def test_tooltip_hover_is_not_interactive(tmp_path: Path) -> None:
    demo, path = _probe(
        tmp_path, "return imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value)"
    )
    assert not demo.classify(path).is_interactive


def test_plain_hover_is_interactive(tmp_path: Path) -> None:
    demo, path = _probe(tmp_path, "return imgui.is_item_hovered()")
    assert demo.classify(path).is_interactive


@pytest.mark.parametrize(
    "body",
    [
        "imgui.begin_child('x')",
        "imgui.begin_table('x', 2)",
        "imgui.invisible_button('x', s)",
        "clipper.begin(3)",
        "return clipper.button('x')",
    ],
)
def test_containers_and_non_imgui_receivers_are_not_interactive(
    tmp_path: Path, body: str
) -> None:
    demo, path = _probe(tmp_path, body)
    assert not demo.classify(path).is_interactive


@pytest.mark.parametrize("body", ["h.fire(e)", "h.dispatch(e)", "x = h.a.fire(e)"])
def test_fire_and_dispatch_match_on_any_receiver(tmp_path: Path, body: str) -> None:
    demo, path = _probe(tmp_path, body)
    assert demo.classify(path).is_interactive


@pytest.mark.parametrize(
    "body", ["return io.mouse_pos", "return imgui.get_io().want_text_input"]
)
def test_io_attribute_reads_are_interactive(tmp_path: Path, body: str) -> None:
    demo, path = _probe(tmp_path, body)
    assert demo.classify(path).is_interactive


def test_widget_with_discarded_result_is_not_interactive(tmp_path: Path) -> None:
    demo, path = _probe(tmp_path, "imgui.selectable('x', False)")
    assert not demo.classify(path).is_interactive


def test_widget_with_used_result_is_interactive(tmp_path: Path) -> None:
    demo, path = _probe(tmp_path, "return imgui.selectable('x', False)")
    assert demo.classify(path).is_interactive


def test_any_source_package_is_scanned(tmp_path: Path) -> None:
    demo, path = _src_file(tmp_path, S + "pty/probe.py", "h.fire(e)")
    assert demo.classify(path).is_interactive


@pytest.mark.parametrize(
    ("relpath", "body", "reason"),
    [
        (D + "bad.py", b"def (\n", "unreadable (SyntaxError)"),
        (S + "hub/bad.py", b"def (\n", "unreadable (SyntaxError)"),
        (S + "hub/latin.py", b"x = '\xff'\n", "unreadable (UnicodeDecodeError)"),
    ],
)
def test_unreadable_files_are_not_waved_through(
    tmp_path: Path, relpath: str, body: bytes, reason: str
) -> None:
    demo, path = _src_file(tmp_path, relpath, body)
    assert reason in demo.classify(path).reasons


def test_deleted_file_is_interactive_and_says_deleted(tmp_path: Path) -> None:
    verdict = DemoClass(tmp_path).classify(S + "hub/gone.py")
    assert (verdict.is_interactive, verdict.reasons) == (
        True,
        ("deleted (not inspectable)",),
    )


def test_summary_reports_pr_level_answers(demo: DemoClass) -> None:
    summary = demo.summarize(["docs/WORKFLOW.md", D + "dock_pill.py"])
    assert "interactive(pr): yes" in summary
    assert "demo_exempt(all): no" in summary


def test_summary_of_only_exempt_paths_is_exempt(demo: DemoClass) -> None:
    assert "demo_exempt(all): yes" in demo.summarize(["docs/WORKFLOW.md"])


def test_summary_refuses_an_empty_change_set(demo: DemoClass) -> None:
    with pytest.raises(ValueError, match="no changed paths"):
        demo.summarize([])


def test_main_refuses_an_empty_change_set(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--base-ref", "HEAD"]) == 1
    assert "no changed paths" in capsys.readouterr().err


def test_main_reports_a_git_failure(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--base-ref", "no-such-ref-demo-class"]) == 1
    assert "git merge-base" in capsys.readouterr().err


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            shutil.which("git") or "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "keep.txt").write_text("keep\n")
    (tmp_path / "old name.txt").write_text("rename me\n")
    (tmp_path / "gone.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def test_change_set_lists_a_path_with_a_space(repo: Path) -> None:
    (repo / "new file.txt").write_text("hi\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add")
    assert ChangeSet(repo, "main").paths() == ["new file.txt"]


def test_change_set_lists_both_sides_of_a_rename(repo: Path) -> None:
    _git(repo, "mv", "old name.txt", "new name.txt")
    _git(repo, "commit", "-q", "-m", "mv")
    assert sorted(ChangeSet(repo, "main").paths()) == ["new name.txt", "old name.txt"]


def test_change_set_lists_a_deleted_file(repo: Path) -> None:
    _git(repo, "rm", "-q", "gone.py")
    _git(repo, "commit", "-q", "-m", "rm")
    assert ChangeSet(repo, "main").paths() == ["gone.py"]


def test_change_set_omits_uncommitted_changes(repo: Path) -> None:
    (repo / "keep.txt").write_text("edited\n")
    assert ChangeSet(repo, "main").paths() == []


def test_change_set_reports_git_stderr(repo: Path) -> None:
    with pytest.raises(GitError, match="unknown-ref"):
        ChangeSet(repo, "unknown-ref").paths()


@pytest.mark.parametrize(
    "call",
    [
        "imgui.menu_item('x', '', False)",
        "imgui.tree_node('x')",
        "imgui.tree_node_ex('x', 0)",
        "imgui.begin_menu('x')",
        "imgui.collapsing_header('x')",
        "imgui.begin_tab_item('x')",
    ],
)
def test_consumed_container_widgets_are_interactive(tmp_path: Path, call: str) -> None:
    demo, path = _probe(tmp_path, f"return {call}")
    assert demo.classify(path).is_interactive


def test_discarded_tree_node_is_not_interactive(tmp_path: Path) -> None:
    demo, path = _probe(tmp_path, "imgui.tree_node('x')")
    assert not demo.classify(path).is_interactive


def test_head_verdict_ignores_uncommitted_edits(repo: Path) -> None:
    source = repo / (S + "display/probe.py")
    source.parent.mkdir(parents=True)
    source.write_text("def f(h, e):\n    h.fire(e)\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "probe")
    source.write_text("pass\n")
    verdict = DemoClass(repo, at_head=True).classify(S + "display/probe.py")
    assert "calls fire()" in verdict.reasons


def test_path_absent_from_head_is_deleted(repo: Path) -> None:
    (repo / "gone.py").unlink()
    _git(repo, "rm", "-q", "--cached", "gone.py")
    _git(repo, "commit", "-q", "-m", "rm")
    (repo / (S + "display")).mkdir(parents=True)
    (repo / (S + "display/new.py")).write_text("def f(h, e):\n    h.fire(e)\n")
    verdict = DemoClass(repo, at_head=True).classify(S + "display/new.py")
    assert verdict.reasons == ("deleted (not inspectable)",)
