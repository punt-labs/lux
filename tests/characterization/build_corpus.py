"""Regenerate the characterization snapshot corpus.

Run this once when a tool's behavior intentionally changes::

    uv run --extra display python -m tests.characterization.build_corpus

Every scenario lives in :data:`SCENARIOS` below. The build invokes each
scenario through :class:`ToolExerciser`, captures the response, and writes
``tests/characterization/snapshots/<scenario_name>.json``.

The replay test in ``test_parity.py`` loads every JSON file in that
directory and asserts the live response matches the recorded one. The
corpus IS the contract; this script is just the recorder.

Determinism note: ``Snapshot.to_file`` writes setups with sorted keys for
diff stability. Before recording each scenario, we round-trip its setup
through JSON so the in-memory dict order matches what replay will see —
otherwise the tool's ``json.dumps`` output would differ by key order
between record and replay.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .exerciser import ToolExerciser
from .snapshot import Snapshot

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["SCENARIOS", "Scenario", "build_all"]


SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


@dataclass(frozen=True, slots=True)
class Scenario:
    """One row in the corpus: a tool, its inputs, and its stub setup.

    The scenario name becomes the snapshot filename. Names must be unique
    and stable — renaming a scenario orphans the previous snapshot and
    creates a new one with no history.
    """

    name: str
    tool: str
    inputs: Mapping[str, object]
    setup: Mapping[str, object]

    def record(self) -> Snapshot:
        """Run the scenario and return the captured :class:`Snapshot`."""
        setup = self.canonical(self.setup)
        inputs = self.canonical(self.inputs)
        response = ToolExerciser.call(self.tool, inputs, setup)
        return Snapshot(
            tool=self.tool,
            inputs=tuple(inputs.items()),
            setup=setup,
            response=response,
        )

    def path(self, root: Path = SNAPSHOT_DIR) -> Path:
        return root / f"{self.name}.json"

    @staticmethod
    def canonical(data: Mapping[str, object]) -> dict[str, object]:
        """Round-trip a mapping through JSON with sorted keys.

        The snapshot file stores ``setup`` with ``sort_keys=True``.
        Replaying means reading that sorted JSON and feeding it back to
        the tool. The record-time call must see the same key order;
        otherwise the tool's own ``json.dumps`` of a dict result would
        print keys in insertion order at record and sorted order at
        replay — and the responses would diverge for nothing more than
        dict iteration order.
        """
        roundtripped: dict[str, object] = json.loads(
            json.dumps(dict(data), sort_keys=True)
        )
        return roundtripped


# ---------------------------------------------------------------------------
# Display lifecycle scenarios — display_mode, set_display_mode, clear, show,
# update. These are the tools that mutate or observe the display's
# session/scene state without going through the introspection query path.
# ---------------------------------------------------------------------------


def _repo_with_display_y() -> str:
    """Return a fixture repo path that has display:y persisted.

    Snapshot tests for ``display_mode`` need a real ``.punt-labs/lux.md``
    file at a known location. We materialise it under the fixture
    directory and keep it in the repo — the test is reading recorded
    state, not the local filesystem.
    """
    return str(SNAPSHOT_DIR / "fixtures" / "repo-y")


def _repo_with_display_n() -> str:
    return str(SNAPSHOT_DIR / "fixtures" / "repo-n")


def _repo_unset() -> str:
    return str(SNAPSHOT_DIR / "fixtures" / "repo-unset")


def _ensure_fixture_repos() -> None:
    """Create the on-disk repo fixtures the display_mode tools read."""
    for repo, mode in (
        (_repo_with_display_y(), "y"),
        (_repo_with_display_n(), "n"),
    ):
        config = Path(repo) / ".punt-labs" / "lux.md"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(f'---\ndisplay: "{mode}"\n---\n', encoding="utf-8")
    unset = Path(_repo_unset())
    unset.mkdir(parents=True, exist_ok=True)
    # Intentionally NO lux.md file in the unset fixture.


LIFECYCLE_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="display_mode-on",
        tool="display_mode",
        inputs={"repo": _repo_with_display_y()},
        setup={"display_running": False},
    ),
    Scenario(
        name="display_mode-off",
        tool="display_mode",
        inputs={"repo": _repo_with_display_n()},
        setup={"display_running": False},
    ),
    Scenario(
        name="display_mode-unset",
        tool="display_mode",
        inputs={"repo": _repo_unset()},
        setup={"display_running": False},
    ),
    Scenario(
        name="set_display_mode-y",
        tool="set_display_mode",
        inputs={"mode": "y", "repo": _repo_with_display_y()},
        setup={"display_running": False, "client": {}},
    ),
    Scenario(
        name="set_display_mode-n",
        tool="set_display_mode",
        inputs={"mode": "n", "repo": _repo_with_display_n()},
        setup={"display_running": False},
    ),
    Scenario(
        name="clear-running",
        tool="clear",
        inputs={},
        setup={"display_running": True, "client": {"clear": {}}},
    ),
    Scenario(
        name="clear-display-off",
        tool="clear",
        inputs={},
        setup={"display_running": False},
    ),
    Scenario(
        name="show-shown",
        tool="show",
        inputs={
            "scene_id": "s1",
            "elements": [
                {"kind": "text", "id": "t1", "content": "Hello", "style": "heading"},
                {"kind": "button", "id": "b1", "label": "OK"},
            ],
        },
        setup={
            "display_running": True,
            "client": {"show": {"return": {"scene_id": "s1", "ts": 1000.0}}},
        },
    ),
    Scenario(
        name="show-framed",
        tool="show",
        inputs={
            "scene_id": "s1",
            "elements": [{"kind": "text", "id": "t1", "content": "Hi"}],
            "frame_id": "dash",
            "frame_title": "Dashboard",
        },
        setup={"display_running": True},
    ),
    Scenario(
        name="show-bad-frame-size",
        tool="show",
        inputs={
            "scene_id": "s1",
            "elements": [],
            "frame_size": [800],
        },
        setup={"display_running": True, "client": {}},
    ),
    Scenario(
        name="show-bad-frame-layout",
        tool="show",
        inputs={
            "scene_id": "s1",
            "elements": [],
            "frame_layout": "grid",
        },
        setup={"display_running": True, "client": {}},
    ),
    Scenario(
        name="show-bad-layout",
        tool="show",
        inputs={
            "scene_id": "s1",
            "elements": [],
            "layout": "diagonal",
        },
        setup={"display_running": True, "client": {}},
    ),
    # ``update`` mutates the Hub's authoritative store first. A ``set`` aimed at
    # an un-installed id is a hard error — a field patch cannot apply to an
    # element that is not there. A ``remove`` of an un-installed id is idempotent:
    # the target is already gone, so the write is accepted and the scene
    # re-pushed. These two scenarios pin that asymmetry under an empty
    # Hub. The scene/element ids never collide with any other scenario's installs.
    Scenario(
        name="update-set-unknown-element",
        tool="update",
        inputs={
            "scene_id": "upd-scene",
            "patches": [{"id": "upd-missing", "set": {"content": "New text"}}],
        },
        setup={"display_running": True, "client": {}},
    ),
    Scenario(
        name="update-remove-unknown-element",
        tool="update",
        inputs={
            "scene_id": "upd-scene",
            "patches": [{"id": "upd-missing", "remove": True}],
        },
        setup={"display_running": True, "client": {}},
    ),
)


# ---------------------------------------------------------------------------
# Composition scenarios — show_table, show_dashboard, register_tool, set_menu.
# These tools assemble higher-level structures (tables, dashboards, menu
# trees) on top of show(); the corpus pins their response shape so the
# migration cannot drift on convenience-wrapper output.
# ---------------------------------------------------------------------------


COMPOSITION_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="show_table-shown",
        tool="show_table",
        inputs={
            "scene_id": "issues",
            "columns": ["ID", "Title", "Status"],
            "rows": [
                ["ISS-1", "Fix login timeout", "Open"],
                ["ISS-2", "Add dark mode", "In Progress"],
            ],
            "filters": [
                {"type": "search", "column": [0, 1], "hint": "Filter..."},
                {"type": "combo", "column": 2, "items": ["All", "Open"]},
            ],
            "detail": {
                "fields": ["ID", "Status"],
                "rows": [["ISS-1", "Open"], ["ISS-2", "In Progress"]],
                "body": ["Login times out.", "Add dark-mode toggle."],
            },
            "title": "Issue Explorer",
        },
        setup={
            "display_running": True,
            "client": {"show": {"return": {"scene_id": "issues", "ts": 1000.0}}},
        },
    ),
    Scenario(
        name="show_table-minimal",
        tool="show_table",
        inputs={
            "scene_id": "tbl-min",
            "columns": ["A"],
            "rows": [["x"]],
        },
        setup={
            "display_running": True,
            "client": {"show": {"return": {"scene_id": "tbl-min", "ts": 1000.0}}},
        },
    ),
    Scenario(
        name="show_dashboard-all-sections",
        tool="show_dashboard",
        inputs={
            "scene_id": "dash",
            "metrics": [
                {"label": "Total", "value": "42"},
                {"label": "Passed", "value": "40"},
            ],
            "charts": [
                {
                    "id": "trend",
                    "title": "Trend",
                    "x_label": "t",
                    "y_label": "v",
                    "series": [
                        {"label": "y", "type": "line", "x": [1, 2], "y": [10, 20]}
                    ],
                }
            ],
            "table_columns": ["Name", "Status"],
            "table_rows": [["test_login", "PASS"]],
            "title": "Dashboard",
        },
        setup={
            "display_running": True,
            "client": {"show": {"return": {"scene_id": "dash", "ts": 1000.0}}},
        },
    ),
    Scenario(
        name="show_dashboard-metrics-only",
        tool="show_dashboard",
        inputs={
            "scene_id": "metrics",
            "metrics": [{"label": "Users", "value": "100"}],
        },
        setup={
            "display_running": True,
            "client": {"show": {"return": {"scene_id": "metrics", "ts": 1000.0}}},
        },
    ),
    Scenario(
        name="show_dashboard-empty",
        tool="show_dashboard",
        inputs={"scene_id": "empty"},
        setup={
            "display_running": True,
            "client": {"show": {"return": {"scene_id": "empty", "ts": 1000.0}}},
        },
    ),
    # set_menu and register_tool are Hub writes now: they store the menu bar in
    # the Hub registry (the replicator pushes it) instead of reaching the
    # display, so their setup declares no client stub. Their string return is
    # unchanged and still pinned here.
    Scenario(
        name="register_tool-basic",
        tool="register_tool",
        inputs={"label": "Run", "tool_id": "run-btn"},
        setup={"session_key": "corpus-register-basic"},
    ),
    Scenario(
        name="register_tool-with-shortcut-and-icon",
        tool="register_tool",
        inputs={
            "label": "Build",
            "tool_id": "build-btn",
            "shortcut": "Cmd+B",
            "icon": "hammer",
        },
        setup={"session_key": "corpus-register-shortcut"},
    ),
    Scenario(
        name="set_menu-ok",
        tool="set_menu",
        inputs={
            "menus": [
                {
                    "label": "Tools",
                    "items": [
                        {"label": "Run", "id": "run-btn"},
                        {"label": "---"},
                        {"label": "Build", "id": "build-btn"},
                    ],
                }
            ]
        },
        setup={"session_key": "corpus-set-menu"},
    ),
)


# ---------------------------------------------------------------------------
# Introspection scenarios — read-only tools that return JSON for an agent
# to consume. Every read endpoint gets at least one snapshot under a known
# fixture response and one under "display not running" so the corpus
# covers both halves of the short-circuit pattern in tools.py.
# ---------------------------------------------------------------------------


INTROSPECTION_SCENARIOS: tuple[Scenario, ...] = (
    # inspect_scene, list_scenes, list_clients, list_menus, list_recent_events,
    # and list_errors now return typed models (Hub-authoritative reads, or the
    # display facts proxied), so they leave the string-parity corpus. Their
    # behavior is pinned by the typed operation tests under tests/operations/.
    # get_display_info, get_window_settings, and get_theme now return typed
    # models (their MCP output schema is derived from the model), so they leave
    # the string-parity corpus. Their behavior is pinned by the typed operation
    # and adapter tests under tests/operations/.
    Scenario(
        name="ping-rtt",
        tool="ping",
        inputs={},
        setup={
            "display_running": True,
            "time": 1000.042,
            "client": {"ping": {"return": {"ts": 1000.0, "display_ts": 1000.005}}},
        },
    ),
    Scenario(
        name="ping-not-running",
        tool="ping",
        inputs={},
        setup={"display_running": False},
    ),
    Scenario(
        name="screenshot-ok",
        tool="screenshot",
        inputs={},
        setup={
            "display_running": True,
            "client": {
                "query": {
                    "method": "screenshot",
                    "result": {"path": "/tmp/lux-screenshot-abc.png"},
                }
            },
        },
    ),
    Scenario(
        name="screenshot-error",
        tool="screenshot",
        inputs={},
        setup={
            "display_running": True,
            "client": {
                "query": {"method": "screenshot", "error": "OpenGL not available"}
            },
        },
    ),
    Scenario(
        name="screenshot-not-running",
        tool="screenshot",
        inputs={},
        setup={"display_running": False},
    ),
)


# ---------------------------------------------------------------------------
# Control scenarios — the set_* tools that mutate display state. Each
# snapshot pins the response shape (not the rendered output, which is
# verified manually); set_menu lives with the composition family because
# it composes menu trees.
# ---------------------------------------------------------------------------


CONTROL_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="set_window_settings-ok",
        tool="set_window_settings",
        inputs={"opacity": 0.9, "font_scale": 1.25, "fps_idle": 30},
        setup={
            "display_running": True,
            "client": {
                "query": {
                    "method": "set_window_settings",
                    "result": {
                        "opacity": 0.9,
                        "font_scale": 1.25,
                        "fps_idle": 30.0,
                        "decorated": True,
                    },
                }
            },
        },
    ),
    Scenario(
        name="set_window_settings-no-params",
        tool="set_window_settings",
        inputs={},
        setup={"display_running": True, "client": {}},
    ),
    Scenario(
        name="set_window_settings-not-running",
        tool="set_window_settings",
        inputs={"opacity": 0.5},
        setup={"display_running": False},
    ),
    Scenario(
        name="set_frame_state-minimize",
        tool="set_frame_state",
        inputs={"frame_id": "f1", "minimized": True},
        setup={
            "display_running": True,
            "client": {
                "query": {
                    "method": "set_frame_state",
                    "result": {"frame_id": "f1", "minimized": True},
                }
            },
        },
    ),
    Scenario(
        name="set_frame_state-expand",
        tool="set_frame_state",
        inputs={"frame_id": "f1", "minimized": False},
        setup={
            "display_running": True,
            "client": {
                "query": {
                    "method": "set_frame_state",
                    "result": {"frame_id": "f1", "minimized": False},
                }
            },
        },
    ),
    Scenario(
        name="set_theme-ok",
        tool="set_theme",
        inputs={"theme": "darcula"},
        setup={
            "display_running": True,
            "client": {
                "query": {"method": "set_theme", "result": {"theme": "darcula"}}
            },
        },
    ),
    Scenario(
        name="set_theme-not-running",
        tool="set_theme",
        inputs={"theme": "darcula"},
        setup={"display_running": False},
    ),
)


# ---------------------------------------------------------------------------
# Interaction scenarios — ``recv`` drains the next queued event or returns the
# literal ``"none"`` when the inbox is empty. The snapshot pair pins both halves
# so the inputs family can verify event delivery survives the migration.
# ---------------------------------------------------------------------------


INTERACTION_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="recv-empty",
        tool="recv",
        inputs={},
        setup={"inbox_empty": True},
    ),
    Scenario(
        name="recv-button-click",
        tool="recv",
        inputs={},
        setup={
            "inbox_event": {
                "topic": "ui.button.click",
                "payload": {
                    "element_id": "btn-submit",
                    "action": "click",
                    "value": True,
                },
            }
        },
    ),
    Scenario(
        name="recv-slider-change",
        tool="recv",
        inputs={},
        setup={
            "inbox_event": {
                "topic": "ui.slider.changed",
                "payload": {
                    "element_id": "slider-temp",
                    "action": "changed",
                    "value": 42.5,
                },
            }
        },
    ),
)


# ---------------------------------------------------------------------------
# Pub-sub scenarios — Agent Subscribe / Publish tools (subscribe, unsubscribe,
# publish). The tools operate on the Hub's in-process SubscriptionRegistry;
# the stub setup only needs to override the session_key ContextVar so each
# scenario runs against a fresh per-connection scope.
# ---------------------------------------------------------------------------


PUBSUB_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="subscribe-ok",
        tool="subscribe",
        inputs={"topic": "work.saved"},
        setup={"display_running": False, "session_key": "corpus-subscribe-ok"},
    ),
    Scenario(
        name="unsubscribe-unknown",
        tool="unsubscribe",
        inputs={"topic": "ghost"},
        setup={"display_running": False, "session_key": "corpus-unsubscribe-unknown"},
    ),
    Scenario(
        name="publish-no-subscribers",
        tool="publish",
        inputs={"topic": "no.one.listening", "payload": {"id": "btn1"}},
        setup={"display_running": False, "session_key": "corpus-publish-empty"},
    ),
)


SCENARIOS: tuple[Scenario, ...] = (
    LIFECYCLE_SCENARIOS
    + COMPOSITION_SCENARIOS
    + INTROSPECTION_SCENARIOS
    + CONTROL_SCENARIOS
    + INTERACTION_SCENARIOS
    + PUBSUB_SCENARIOS
)


def build_all(scenarios: Sequence[Scenario] = SCENARIOS) -> list[Path]:
    """Record every scenario and return the list of written paths."""
    _ensure_fixture_repos()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for scenario in scenarios:
        snap = scenario.record()
        snap.to_file(scenario.path())
        written.append(scenario.path())
    return written


if __name__ == "__main__":
    paths = build_all()
    for path in paths:
        sys.stdout.write(f"wrote {path}\n")
