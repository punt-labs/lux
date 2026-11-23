"""Classify the paths a PR changes for the demo gate in docs/WORKFLOW.md.

Per path: interactive (reads input or decides what input does), rendering
(what the Display paints), exempt (needs no demo), or none. Python files are
decided by AST, never by grep, so a tooltip hover is not an interaction.
A path prints one kind, by precedence: exempt, then interactive, then rendering.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar, Literal, Protocol, Self

DemoKind = Literal["interactive", "rendering", "exempt", "none"]


@dataclass(frozen=True, slots=True)
class DemoVerdict:
    """What the demo gate decided about one changed path."""

    path: str
    is_interactive: bool
    is_rendering: bool
    is_exempt: bool
    reasons: tuple[str, ...]

    SHOWN_REASONS: ClassVar[int] = 3

    @property
    def kind(self) -> DemoKind:
        """The one kind this path prints: exempt, then interactive, then rendering."""
        if self.is_exempt:
            return "exempt"
        if self.is_interactive:
            return "interactive"
        if self.is_rendering:
            return "rendering"
        return "none"

    def render(self) -> str:
        shown = self.reasons[: self.SHOWN_REASONS]
        more = len(self.reasons) - len(shown)
        parts = [*shown, f"+{more} more"] if more else list(shown)
        because = f" [{'; '.join(parts)}]" if parts else ""
        return f"{self.path}: {self.kind}{because}"


class ImguiInputScan(ast.NodeVisitor):
    """Collect what in one module reads input or forwards an interaction."""

    # ImGui queries that read the pointer or keyboard directly (any receiver).
    INPUT_QUERIES: ClassVar[frozenset[str]] = frozenset(
        {
            "is_item_clicked",
            "is_item_active",
            "is_window_hovered",
            "get_mouse_pos",
            "set_keyboard_focus_here",
            "begin_popup_modal",
        }
    )
    INPUT_QUERY_PREFIXES: ClassVar[tuple[str, ...]] = ("is_mouse_", "is_key_")
    # Widgets that return a changed flag, matched only on the ``imgui`` receiver;
    # ``begin`` is a top-level window (begin_child, begin_table, begin_group are
    # different names, and ``clipper.begin(n)`` is not on ``imgui``).
    WIDGET_CALLS: ClassVar[frozenset[str]] = frozenset(
        {
            "button",
            "checkbox",
            "combo",
            "radio_button",
            "selectable",
            "begin",
            "menu_item",
            "begin_menu",
            "tree_node",
            "tree_node_ex",
            "collapsing_header",
            "begin_tab_item",
            "tab_item_button",
        }
    )
    WIDGET_PREFIXES: ClassVar[tuple[str, ...]] = (
        "slider_",
        "drag_",
        "input_text",
        "color_edit",
        "color_picker",
    )
    IMGUI_RECEIVER: ClassVar[str] = "imgui"
    # ``is_item_hovered`` is an input query unless it carries this flag: a
    # tooltip hover decides what to show, not what a click does.
    TOOLTIP_FLAG: ClassVar[str] = "for_tooltip"
    HOVER_QUERY: ClassVar[str] = "is_item_hovered"
    # Any receiver: forwarding an interaction to its handler.
    HANDLER_CALLS: ClassVar[frozenset[str]] = frozenset({"fire", "dispatch", "clicked"})
    # ``io.key_ctrl``, ``io.mouse_pos``, ``io.want_text_input``: reads, not calls.
    IO_PREFIXES: ClassVar[tuple[str, ...]] = ("key_", "mouse_", "want_")
    # An event class: ButtonClicked, ValueChanged, ServicedClick, ... (not ClickLatency)
    EVENT_NAME: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?=[A-Z])\w*(Click|Clicked|Changed|Pressed|Submitted)$"
    )
    FORWARDING_NAMES: ClassVar[frozenset[str]] = frozenset(
        {"interaction_delivery", "pending_interactions", "frame_commands", "auto_click"}
    )

    _reasons: list[str]
    _discarded: set[int]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._reasons = []
        self._discarded = set()
        return self

    def scan(self, tree: ast.AST) -> tuple[str, ...]:
        self._reasons = []
        self._discarded = set()
        self.visit(tree)
        return tuple(dict.fromkeys(self._reasons))

    def visit_Expr(self, node: ast.Expr) -> None:
        # A widget call used as a bare statement discards its changed flag:
        # the widget is there to lay out or detect hover, not to read input.
        if isinstance(node.value, ast.Call):
            self._discarded.add(id(node.value))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            reason = self._call_reason(node, node.func)
            if reason:
                self._reasons.append(reason)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_io(node.value) and node.attr.startswith(self.IO_PREFIXES):
            self._reasons.append(f"reads io.{node.attr}")
        self._note_name(node.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._note_name(node.id)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self._note_name(alias.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._note_name(node.name)
        # CamelCase -> snake_case would need a regex; squeezing out the
        # underscores on both sides compares the same words.
        squashed = node.name.lower()
        for name in sorted(self.FORWARDING_NAMES):
            if name.replace("_", "") in squashed:
                self._reasons.append(f"class {node.name} forwards interactions")
        self.generic_visit(node)

    def _note_name(self, name: str) -> None:
        if self.EVENT_NAME.match(name):
            self._reasons.append(f"references event {name}")

    @staticmethod
    def _is_io(node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id == "io"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return node.func.attr == "get_io"
        return isinstance(node, ast.Attribute) and node.attr == "io"

    def _call_reason(self, node: ast.Call, func: ast.Attribute) -> str:
        attr = func.attr
        if attr in self.HANDLER_CALLS:
            return f"calls {attr}()"
        if attr == self.HOVER_QUERY:
            return "" if self._is_tooltip_hover(node) else f"calls {attr}()"
        if attr in self.INPUT_QUERIES or attr.startswith(self.INPUT_QUERY_PREFIXES):
            return f"calls {attr}()"
        is_widget = attr in self.WIDGET_CALLS or attr.startswith(self.WIDGET_PREFIXES)
        on_imgui = (
            isinstance(func.value, ast.Name) and func.value.id == self.IMGUI_RECEIVER
        )
        if is_widget and on_imgui and id(node) not in self._discarded:
            return f"calls {attr}()"
        return ""

    def _is_tooltip_hover(self, node: ast.Call) -> bool:
        operands = [*node.args, *(kw.value for kw in node.keywords)]
        return any(
            isinstance(sub, ast.Attribute) and sub.attr == self.TOOLTIP_FLAG
            for operand in operands
            for sub in ast.walk(operand)
        )


class Source(Protocol):
    """Where a changed file's text comes from."""

    def read(self, path: str) -> str:
        """Return the file's text; FileNotFoundError when it does not exist."""
        ...


class WorkingTree:
    """Files as they are on disk."""

    _root: Path

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    def read(self, path: str) -> str:
        return (self._root / path).read_text(encoding="utf-8")


class CommittedHead:
    """Files as committed at HEAD, so the verdict is for the head the demo names."""

    _changes: ChangeSet

    def __new__(cls, changes: ChangeSet) -> Self:
        self = super().__new__(cls)
        self._changes = changes
        return self

    def read(self, path: str) -> str:
        return self._changes.read_head(path)


class DemoClass:
    """Decide interactive / rendering / exempt for repo-relative paths."""

    SRC: ClassVar[str] = "src/punt_lux/"
    RENDERING_PREFIXES: ClassVar[tuple[str, ...]] = (
        SRC + "display/",
        SRC + "wire/model/elements/",
        SRC + "wire/model/compositions/",
        SRC + "applets/",
    )
    INTERACTIVE_PREFIXES: ClassVar[tuple[str, ...]] = (
        SRC + "wire/model/handlers/",
        SRC + "wire/model/compositions/",
        "plugin/",
    )
    EXEMPT_PREFIXES: ClassVar[tuple[str, ...]] = ("docs/", "tests/", ".github/")
    BEHAVIOR_PREFIXES: ClassVar[tuple[str, ...]] = ("plugin/", ".github/workflows/")
    # Root ratchet files: .oo-*, .suppression-* and .layer-* baselines and audits.
    RATCHET_FILE: ClassVar[re.Pattern[str]] = re.compile(
        r"^\.(oo|suppression|layer)-([\w-]*-)?(baseline\.json|audit\.jsonl)$"
    )
    # A module named for input or clicks decides what input does.
    STEM_WORDS: ClassVar[tuple[str, ...]] = ("click", "input", "interaction")

    _source: Source
    _scan: ImguiInputScan

    def __new__(cls, source: Source) -> Self:
        self = super().__new__(cls)
        self._source = source
        self._scan = ImguiInputScan()
        return self

    @classmethod
    def on_disk(cls, root: Path) -> Self:
        """Classify the files as they are in the working tree."""
        return cls(WorkingTree(root))

    @classmethod
    def at_head(cls, root: Path) -> Self:
        """Classify the files as committed at HEAD."""
        return cls(CommittedHead(ChangeSet(root, "HEAD")))

    def classify(self, path: str) -> DemoVerdict:
        reasons: list[str] = []
        is_rendering = path.startswith(self.RENDERING_PREFIXES)
        is_interactive = False
        if path.startswith(self.INTERACTIVE_PREFIXES):
            is_interactive = True
            reasons.append("interactive by path")
        elif path.endswith(".py") and path.startswith(self.SRC):
            reasons.extend(self._ast_reasons(path))
            is_interactive = bool(reasons)
        return DemoVerdict(
            path, is_interactive, is_rendering, self._is_exempt(path), tuple(reasons)
        )

    def summarize(self, paths: list[str]) -> str:
        if not paths:
            raise ValueError("no changed paths to classify")
        verdicts = [self.classify(path) for path in sorted(paths)]
        lines = [v.render() for v in verdicts]
        live = [v for v in verdicts if not v.is_exempt]
        lines.append(
            f"interactive(pr): {'yes' if any(v.is_interactive for v in live) else 'no'}"
        )
        lines.append(
            f"rendering(pr): {'yes' if any(v.is_rendering for v in live) else 'no'}"
        )
        lines.append(f"demo_exempt(all): {'no' if live else 'yes'}")
        return "\n".join(lines)

    def _is_exempt(self, path: str) -> bool:
        if path.startswith(self.BEHAVIOR_PREFIXES):
            return False
        return (
            path.endswith(".md")
            or path.startswith(self.EXEMPT_PREFIXES)
            or ("/" not in path and bool(self.RATCHET_FILE.match(path)))
        )

    def _ast_reasons(self, path: str) -> list[str]:
        reasons = self._module_reasons(path)
        try:
            tree = ast.parse(self._source.read(path))
        except FileNotFoundError:
            # A deleted file cannot be inspected; a gate must not wave it through.
            return [*reasons, "deleted (not inspectable)"]
        except (OSError, SyntaxError, UnicodeError, GitError) as error:
            return [*reasons, f"unreadable ({error.__class__.__name__})"]
        return [*reasons, *self._scan.scan(tree)]

    def _module_reasons(self, path: str) -> list[str]:
        stem = PurePosixPath(path).stem
        if stem in ImguiInputScan.FORWARDING_NAMES or any(
            word in stem for word in self.STEM_WORDS
        ):
            return ["module is named for interactions"]
        return []


class GitError(RuntimeError):
    """A git command the change set needs failed."""


class ChangeSet:
    """The paths a branch changes relative to a base ref."""

    _root: Path
    _base_ref: str

    def __new__(cls, root: Path, base_ref: str) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._base_ref = base_ref
        return self

    def paths(self) -> list[str]:
        """Return paths changed between the merge base with the base ref and HEAD.

        Covers committed changes only, so the verdict is for the head the demo
        comment names. Omits uncommitted and untracked files. A rename lists
        both its old and new path; a deletion lists the deleted path.
        """
        base = self._git("merge-base", self._base_ref, "HEAD").strip()
        diff = self._git("diff", "--name-only", "-z", "--no-renames", base, "HEAD")
        return [path for path in diff.split("\0") if path]

    def read_head(self, path: str) -> str:
        """Return the file as committed at HEAD; FileNotFoundError if absent there."""
        try:
            return self._git("show", f"HEAD:{path}")
        except GitError as error:
            if "in 'HEAD'" in str(error):
                raise FileNotFoundError(path) from error
            raise

    def _git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=self._root,
            capture_output=True,
            encoding="utf-8",
            errors="strict",
            check=False,
        )
        if done.returncode:
            raise GitError(f"git {' '.join(args)}: {done.stderr.strip()}")
        return done.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("paths", nargs="*", help="classify these instead of the diff")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        paths = args.paths or ChangeSet(root, args.base_ref).paths()
        demo = DemoClass.on_disk(root) if args.paths else DemoClass.at_head(root)
        print(demo.summarize(paths))
    except (OSError, GitError, ValueError) as error:
        print(f"demo-class failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
