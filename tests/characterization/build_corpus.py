"""Regenerate the characterization snapshot corpus.

Run this once when a tool's behavior intentionally changes::

    uv run --extra display python -m tests.characterization.build_corpus

Every scenario lives in :data:`SCENARIOS` below. The build invokes each
scenario through :class:`ToolExerciser`, captures the response, and writes
``tests/characterization/snapshots/<scenario_name>.json``.

The replay test in ``test_parity.py`` loads every JSON file in that
directory and asserts the live response matches the recorded one. The
corpus IS the contract; this script is just the recorder.
"""

from __future__ import annotations

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
        response = ToolExerciser.call(self.tool, self.inputs, self.setup)
        return Snapshot(
            tool=self.tool,
            inputs=tuple(self.inputs.items()),
            setup=dict(self.setup),
            response=response,
        )

    def path(self, root: Path = SNAPSHOT_DIR) -> Path:
        return root / f"{self.name}.json"


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
        setup={"display_running": True, "client": {}},
    ),
    Scenario(
        name="clear-not-running",
        tool="clear",
        inputs={},
        setup={"display_running": False},
    ),
    Scenario(
        name="show-ack",
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
        name="show-timeout",
        tool="show",
        inputs={
            "scene_id": "s1",
            "elements": [{"kind": "text", "id": "t1", "content": "Hi"}],
        },
        setup={"display_running": True, "client": {"show": {"return": None}}},
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
        name="update-ack",
        tool="update",
        inputs={
            "scene_id": "s1",
            "patches": [{"id": "t1", "set": {"content": "New text"}}],
        },
        setup={
            "display_running": True,
            "client": {"update": {"return": {"scene_id": "s1", "ts": 1000.0}}},
        },
    ),
    Scenario(
        name="update-timeout",
        tool="update",
        inputs={
            "scene_id": "s1",
            "patches": [{"id": "t1", "remove": True}],
        },
        setup={"display_running": True, "client": {"update": {"return": None}}},
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
        name="show_table-ack",
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
    Scenario(
        name="register_tool-basic",
        tool="register_tool",
        inputs={"label": "Run", "tool_id": "run-btn"},
        setup={
            "display_running": True,
            "client": {},
            "session_key": "corpus-register-basic",
        },
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
        setup={
            "display_running": True,
            "client": {},
            "session_key": "corpus-register-shortcut",
        },
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
        setup={"display_running": True, "client": {}},
    ),
)


SCENARIOS: tuple[Scenario, ...] = LIFECYCLE_SCENARIOS + COMPOSITION_SCENARIOS


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
