"""Classify the paths a PR changes for the demo gate in docs/WORKFLOW.md.

Per path: interactive (reads input or decides what input does), rendering
(what the Display paints), exempt (needs no demo), or none. Python files are
decided by AST, never by grep, so a tooltip hover is not an interaction.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar, Literal, Self

DemoKind = Literal["interactive", "rendering", "exempt", "none"]


@dataclass(frozen=True)
class DemoVerdict:
    """What the demo gate decided about one changed path."""

    path: str
    is_interactive: bool
    is_rendering: bool
    is_exempt: bool
    reasons: tuple[str, ...]

    @property
    def kind(self) -> DemoKind:
        if self.is_exempt:
            return "exempt"
        if self.is_interactive:
            return "interactive"
        if self.is_rendering:
            return "rendering"
        return "none"

    def render(self) -> str:
        flags = ", ".join(
            name
            for name, on in (
                ("interactive", self.is_interactive),
                ("rendering", self.is_rendering),
                ("exempt", self.is_exempt),
            )
            if on
        )
        because = f" [{'; '.join(self.reasons)}]" if self.reasons else ""
        return f"{self.path}: {flags or 'none'}{because}"


class ImguiInputScan(ast.NodeVisitor):
    """Collect the calls and classes in one module that read or forward input."""

    # ImGui queries that read the pointer or keyboard directly.
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
    # Widgets that return a changed flag; ``begin`` is a top-level window only
    # (begin_child, begin_table and begin_group are different attribute names).
    WIDGET_CALLS: ClassVar[frozenset[str]] = frozenset(
        {"button", "checkbox", "combo", "radio_button", "selectable", "begin"}
    )
    WIDGET_PREFIXES: ClassVar[tuple[str, ...]] = (
        "slider_",
        "drag_",
        "input_text",
        "color_edit",
        "color_picker",
    )
    # ``is_item_hovered`` is an input query unless it carries this flag: a
    # tooltip hover decides what to show, not what a click does.
    TOOLTIP_FLAG: ClassVar[str] = "for_tooltip"
    HOVER_QUERY: ClassVar[str] = "is_item_hovered"
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

    def scan(self, source: str) -> tuple[str, ...]:
        self._reasons = []
        self._discarded = set()
        self.visit(ast.parse(source))
        return tuple(dict.fromkeys(self._reasons))

    def visit_Expr(self, node: ast.Expr) -> None:
        # A widget call used as a bare statement discards its changed flag:
        # the widget is there to lay out or detect hover, not to read input.
        if isinstance(node.value, ast.Call):
            self._discarded.add(id(node.value))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            reason = self._call_reason(node, node.func.attr)
            if reason:
                self._reasons.append(reason)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # CamelCase -> snake_case would need a regex; squeezing out the
        # underscores on both sides compares the same words.
        squashed = node.name.lower()
        for name in sorted(self.FORWARDING_NAMES):
            if name.replace("_", "") in squashed:
                self._reasons.append(f"class {node.name} forwards interactions")
        self.generic_visit(node)

    def _call_reason(self, node: ast.Call, attr: str) -> str:
        if attr == self.HOVER_QUERY:
            return "" if self._is_tooltip_hover(node) else f"calls {attr}()"
        is_query = attr in self.INPUT_QUERIES or attr.startswith(
            self.INPUT_QUERY_PREFIXES
        )
        is_widget = attr in self.WIDGET_CALLS or attr.startswith(self.WIDGET_PREFIXES)
        if is_query or (is_widget and id(node) not in self._discarded):
            return f"calls {attr}()"
        return ""

    def _is_tooltip_hover(self, node: ast.Call) -> bool:
        operands = [*node.args, *(kw.value for kw in node.keywords)]
        return any(
            isinstance(sub, ast.Attribute) and sub.attr == self.TOOLTIP_FLAG
            for operand in operands
            for sub in ast.walk(operand)
        )


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
    RATCHET_FILES: ClassVar[frozenset[str]] = frozenset(
        {
            ".oo-baseline.json",
            ".oo-audit.jsonl",
            ".oo-coupling-baseline.json",
            ".oo-coupling-audit.jsonl",
            ".layer-baseline.json",
        }
    )
    HANDLER_CALLS: ClassVar[frozenset[str]] = frozenset({"fire", "dispatch"})

    _root: Path
    _scan: ImguiInputScan

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._scan = ImguiInputScan()
        return self

    def classify(self, path: str) -> DemoVerdict:
        reasons: list[str] = []
        is_exempt = self._is_exempt(path)
        is_rendering = path.startswith(self.RENDERING_PREFIXES)
        is_interactive = False
        if path.startswith(self.INTERACTIVE_PREFIXES):
            is_interactive = True
            reasons.append("interactive by path")
        elif path.endswith(".py") and path.startswith(
            (self.SRC + "display/", self.SRC + "hub/")
        ):
            found = self._ast_reasons(path)
            is_interactive = bool(found)
            reasons.extend(found)
        return DemoVerdict(
            path, is_interactive, is_rendering, is_exempt, tuple(reasons)
        )

    def summarize(self, paths: list[str]) -> str:
        verdicts = [self.classify(path) for path in sorted(paths)]
        lines = [v.render() for v in verdicts]
        interactive = [v.path for v in verdicts if v.is_interactive and not v.is_exempt]
        rendering = [v.path for v in verdicts if v.is_rendering and not v.is_exempt]
        lines.append(f"interactive(pr): {'yes' if interactive else 'no'}")
        lines.append(f"rendering(pr): {'yes' if rendering else 'no'}")
        lines.append(
            f"demo_exempt(all): {'yes' if all(v.is_exempt for v in verdicts) else 'no'}"
        )
        return "\n".join(lines)

    def _is_exempt(self, path: str) -> bool:
        if path.startswith(self.BEHAVIOR_PREFIXES):
            return False
        name = PurePosixPath(path).name
        return (
            path.endswith(".md")
            or path.startswith(self.EXEMPT_PREFIXES)
            or name in self.RATCHET_FILES
        )

    def _ast_reasons(self, path: str) -> list[str]:
        try:
            source = (self._root / path).read_text(encoding="utf-8")
            if path.startswith(self.SRC + "hub/"):
                return self._handler_reasons(source)
            return [*self._module_reasons(path), *self._scan.scan(source)]
        except (OSError, SyntaxError, UnicodeError) as error:
            # A gate that cannot read a file must not wave it through.
            return [f"unreadable ({error.__class__.__name__})"]

    def _module_reasons(self, path: str) -> list[str]:
        stem = PurePosixPath(path).stem
        if stem in ImguiInputScan.FORWARDING_NAMES or "interaction" in stem:
            return ["module forwards interactions"]
        return []

    def _handler_reasons(self, source: str) -> list[str]:
        calls = {
            node.func.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        return [f"calls {name}()" for name in sorted(calls & self.HANDLER_CALLS)]


def changed_paths(root: Path, base_ref: str) -> list[str]:
    """Return paths changed since the merge base with ``base_ref``."""
    base = subprocess.run(
        ["git", "merge-base", base_ref, "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--name-only", base],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return diff.split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("paths", nargs="*", help="classify these instead of the diff")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        paths = args.paths or changed_paths(root, args.base_ref)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"demo-class failed: {error}")
        return 1
    print(DemoClass(root).summarize(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
