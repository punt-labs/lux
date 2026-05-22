"""Manual smoke test — render every supported element kind across 7 frames.

Invoked as:

    uv run --extra display python scripts/manual_smoke.py

Requires luxd + lux-display already running.  Will NOT auto-spawn —
the script fails loudly (exit 2) when the prerequisite isn't met
because silent auto-spawn would hide the operator setup mistake the
script is meant to surface.

Sends 7 themed scenes — basics, inputs, layout, graphics, table, plot,
modal — and prints a cross-reference manifest to stdout that names
each frame's contents and what the operator should look for.  Does
NOT call ``clear()`` — items stay on screen for visual inspection.

Exit codes:

* ``0`` — every frame acked
* ``1`` — at least one frame's ack timed out (no transport error)
* ``2`` — at least one frame raised a transport error (broken socket,
  dead listener, etc.)
* ``3`` — both timeouts AND transport errors
* ``4`` — PNG asset preparation failed before the display was contacted
* ``5`` — element-kind coverage mismatch — the union of every frame's
  kinds did not match the 24-kind expected set; a frame builder dropped
  or duplicated an element kind

The manifest prints in every exit path except ``4`` (PNG asset failed
before frames exist).  When no frame was ever sent (coverage mismatch,
connect failure) the closing line names that fact instead of falsely
claiming items remain on screen.
"""

from __future__ import annotations

import io
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Self

from PIL import Image, UnidentifiedImageError

from punt_lux.display_client import DisplayClient
from punt_lux.protocol import Element
from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    DrawElement,
    GroupElement,
    ImageElement,
    InputNumberElement,
    InputTextElement,
    MarkdownElement,
    ModalElement,
    PlotElement,
    ProgressElement,
    RadioElement,
    SelectableElement,
    SeparatorElement,
    SliderElement,
    SpinnerElement,
    TabBarElement,
    TableDetail,
    TableElement,
    TableFilter,
    TextElement,
    TreeElement,
    WindowElement,
)
from punt_lux.protocol.elements.draw_bounds import Radius
from punt_lux.protocol.elements.draw_commands_curve import BezierCubic
from punt_lux.protocol.elements.draw_commands_line import Line, Polyline
from punt_lux.protocol.elements.draw_commands_shape import Circle, Rect, Triangle
from punt_lux.protocol.elements.draw_commands_text import TextGlyph
from punt_lux.protocol.elements.draw_values import Color, Point2, Thickness


@dataclass(frozen=True, slots=True)
class FrameSpec:
    """One frame in the smoke test — the scene plus its manifest entry.

    ``elements`` is the source of truth for what's on screen.  ``kinds``
    is *not* stored — :class:`SmokeRunner` derives it by walking the
    elements via :func:`_collect_kinds` so a stale hardcoded tuple can't
    lie about what the frame actually contains.  ``look_for`` is
    narrative for the operator and stays hardcoded.
    """

    frame_id: str
    title: str
    elements: list[Element]
    look_for: str
    warn_before_send: str | None = None  # PY-TS-14: absent = no operator warning


@dataclass(frozen=True, slots=True)
class RunResult:
    """Result of a :meth:`SmokeRunner.run` call.

    ``missed_acks`` are frame ids whose ``client.show()`` returned
    ``None`` (ack timeout).  ``transport_errors`` are frame ids paired
    with the exception message that broke the send (broken socket,
    dead listener, etc.).
    """

    missed_acks: list[str] = field(default_factory=list)
    transport_errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """Return the 2-bit OR of missed-acks (1) and transport-errors (2)."""
        code = 0
        if self.missed_acks:
            code |= 1
        if self.transport_errors:
            code |= 2
        return code


# The 24 known element kinds covered by this smoke test.  Used for the
# top-of-main sanity assertion — if a frame builder loses an element kind,
# the assertion fires before the display is contacted.
_EXPECTED_KINDS: Final = frozenset(
    {
        "button",
        "checkbox",
        "collapsing_header",
        "color_picker",
        "combo",
        "draw",
        "group",
        "image",
        "input_number",
        "input_text",
        "markdown",
        "modal",
        "plot",
        "progress",
        "radio",
        "selectable",
        "separator",
        "slider",
        "spinner",
        "tab_bar",
        "table",
        "text",
        "tree",
        "window",
    }
)


# ---------------------------------------------------------------------------
# Element-tree walkers — primitives toolkit, PY-OO-7 exception:
# stateless, no FrameSpec/SmokeRunner vocabulary.
# ---------------------------------------------------------------------------


def _collect_kinds(elements: list[Element]) -> frozenset[str]:
    """Walk every element (and its containers) and return the set of kinds.

    Recurses into ``children`` (Group, CollapsingHeader, Window, Modal),
    ``pages`` (Group with ``layout="paged"``), ``tabs[].children``
    (TabBar), and ``nodes[].children`` (Tree).  ``DrawElement.commands``
    are not separate elements — they're commands of the ``draw`` kind
    and contribute only ``"draw"`` itself.
    """
    kinds: set[str] = set()
    for elem in elements:
        kinds.add(elem.kind)
        if isinstance(
            elem,
            GroupElement | CollapsingHeaderElement | WindowElement | ModalElement,
        ):
            kinds |= _collect_kinds(elem.children)
        if isinstance(elem, GroupElement):
            # GroupElement(layout="paged") puts indexed content panels in
            # ``pages`` — recurse into every page so paged content counts
            # toward coverage.
            for page in elem.pages:
                if isinstance(page, list):
                    kinds |= _collect_kinds(page)
        if isinstance(elem, TabBarElement):
            for tab in elem.tabs:
                # Wire boundary — TabBarElement.tabs holds raw dicts in the
                # protocol; children inside each tab are Element instances.
                tab_children = tab.get("children", [])
                if isinstance(tab_children, list):
                    kinds |= _collect_kinds(tab_children)
        if isinstance(elem, TreeElement):
            kinds |= _collect_tree_node_kinds(elem.nodes)
    return frozenset(kinds)


def _collect_tree_node_kinds(nodes: list[dict[str, object]]) -> frozenset[str]:
    """Walk Tree nodes recursively; Tree leaves carry no element kinds."""
    kinds: set[str] = set()
    for node in nodes:
        children = node.get("children", [])
        if isinstance(children, list):
            # Tree node children are dicts in the same shape as the parent,
            # not Element instances — recurse via this helper, not _collect_kinds.
            typed_children: list[dict[str, object]] = [
                c for c in children if isinstance(c, dict)
            ]
            kinds |= _collect_tree_node_kinds(typed_children)
    return frozenset(kinds)


# ---------------------------------------------------------------------------
# PNG asset generation — primitives toolkit, PY-OO-7 exception:
# stateless, no FrameSpec/SmokeRunner vocabulary.  We hand-roll a tiny PNG
# so the script doesn't pull Pillow just to write an asset (Pillow is in
# the [display] extra and used only for round-trip validation).
# ---------------------------------------------------------------------------


_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    """Build one PNG chunk (length, tag, payload, CRC) — used by _make_png."""
    crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)


def _make_png(width: int, height: int) -> bytes:
    """Return PNG bytes for an RGB image with a 2-stripe pattern."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter byte: None
        for x in range(width):
            if (x // 4 + y // 4) % 2 == 0:
                rows += b"\x33\x99\xff"  # blue
            else:
                rows += b"\xff\xcc\x33"  # gold
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(rows), 9)
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _resolve_tmp_dir() -> Path:
    """Return the repo's ``.tmp/`` directory, anchored to the script's location.

    Resolves via ``__file__`` so the path is the same whether the script
    is invoked from the repo root or any other working directory.
    Project invariant: ``.tmp/`` is the only scratch location; no
    fallback to the system temp directory.
    """
    return Path(__file__).resolve().parent.parent / ".tmp"


def _write_sample_png() -> Path:
    """Write a 32x32 PNG atomically to ``.tmp/`` and return its path.

    Writes to ``<path>.png.tmp`` first then ``Path.replace``s into place —
    a partial PNG file is never visible to a concurrent reader, even if
    the process dies mid-write.

    Validates the generated bytes through ``PIL.Image.verify()`` before
    writing — a corrupted PNG (e.g. wrong byte length, bad CRC) raises
    here instead of failing silently on the display side.

    Raises ``SystemExit(4)`` on any ``OSError`` (permission denied, no
    space) or PNG validation failure, so the asset problem surfaces
    before the display is contacted.  Prints the resolved path to
    stderr so the operator knows which file was used.
    """
    out_dir = _resolve_tmp_dir()
    path = out_dir / "lux-manual-smoke-sample.png"
    tmp = path.with_suffix(".png.tmp")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        data = _make_png(32, 32)
        # PIL.Image.verify() requires a fresh handle — verifying the bytes
        # closes the file pointer, so re-open if we ever need to read the
        # image again.  Here we only need the verify pass.
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        tmp.write_bytes(data)
        tmp.replace(path)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        print(f"PNG asset failed at {path}: {exc}", file=sys.stderr)
        raise SystemExit(4) from exc
    print(f"smoke asset: {path}", file=sys.stderr)
    return path


# ---------------------------------------------------------------------------
# SmokeRunner — owns frame construction, manifest emission, send loop.
# ---------------------------------------------------------------------------


class SmokeRunner:
    """Build the seven smoke-test frames, verify coverage, drive the send loop.

    Frame builders are methods that share the runner's vocabulary
    (every one returns a :class:`FrameSpec`).  The previous module-level
    helpers were a PY-OO-7 smell: a class plus a cluster of free
    functions all producing instances of the class.  Now each is a
    method; the runner is the single seam between the test data and
    the display.
    """

    _image_path: Path
    _frames: list[FrameSpec]

    def __new__(cls, image_path: Path) -> Self:
        self = super().__new__(cls)
        self._image_path = image_path
        self._frames = [
            self._build_basics(),
            self._build_inputs(),
            self._build_layout(),
            self._build_graphics(),
            self._build_table(),
            self._build_plot(),
            self._build_modal(),
        ]
        return self

    # -- public surface ----------------------------------------------------

    @property
    def frames(self) -> list[FrameSpec]:
        """Return the seven FrameSpecs in send order (modal last)."""
        return list(self._frames)

    def verify_coverage(self) -> str | None:
        """Return an error message if coverage doesn't match expected, else None.

        Compares the union of every frame's kinds against
        :data:`_EXPECTED_KINDS`.  Returning a string instead of raising
        keeps the caller in charge of exit-code dispatch.
        """
        actual = frozenset().union(*(_collect_kinds(f.elements) for f in self._frames))
        missing = _EXPECTED_KINDS - actual
        extra = actual - _EXPECTED_KINDS
        if not missing and not extra:
            return None
        return (
            f"smoke coverage mismatch — expected {len(_EXPECTED_KINDS)} kinds, "
            f"got {len(actual)} "
            f"(missing: {sorted(missing)}; extra: {sorted(extra)})"
        )

    def print_manifest(self, *, attempted: bool = True) -> None:
        """Print the cross-reference manifest to stdout.

        Kinds are derived from each frame's elements via
        :func:`_collect_kinds` — the manifest is always in sync with what
        was sent.  The closing line is conditional on ``attempted``: when
        no frame ever reached ``client.show()`` (connect failed, coverage
        mismatch) the "Items remain on screen for inspection" claim
        would be a lie.
        """
        print("=" * 72)
        print("Lux manual smoke test — element coverage manifest")
        print("=" * 72)
        print()
        total_kinds: set[str] = set()
        for i, spec in enumerate(self._frames, start=1):
            frame_kinds = _collect_kinds(spec.elements)
            total_kinds |= frame_kinds
            print(f"Frame {i}: {spec.title}")
            print(f"  frame_id : {spec.frame_id}")
            print(f"  kinds    : {', '.join(sorted(frame_kinds))}")
            print(f"  look for : {spec.look_for}")
            print()
        print("-" * 72)
        print(f"Total element kinds covered: {len(total_kinds)}")
        print(f"  {', '.join(sorted(total_kinds))}")
        print()
        print("DrawElement (frame 4) additionally exercises every draw-command kind:")
        print("  line, rect, circle, triangle, polyline, bezier_cubic, text")
        print()
        if attempted:
            print(
                "Display has NOT been cleared. Items remain on screen for inspection."
            )
        else:
            print("No frame was sent — manifest describes intended contents only.")
        print("=" * 72)

    def run(self, client: DisplayClient) -> RunResult:
        """Send every frame, return a :class:`RunResult` summary.

        Tries every frame even if earlier ones fail — partial coverage
        on screen is more useful than a clean abort.  ``warn_before_send``
        prints to stderr before the corresponding frame is dispatched so
        the operator knows e.g. a modal is about to take over.

        Accumulates failures into local lists and constructs the
        ``RunResult`` once at the end.  Mutating ``frozen=True``
        instance fields (even mutable lists) breaks the frozen
        contract — callers see a dataclass whose lists are still being
        populated under the rug.
        """
        missed_acks: list[str] = []
        transport_errors: list[tuple[str, str]] = []
        for spec in self._frames:
            if spec.warn_before_send is not None:
                print(spec.warn_before_send, file=sys.stderr)
            try:
                ack = client.show(
                    scene_id=spec.frame_id,
                    elements=spec.elements,
                    frame_id=spec.frame_id,
                    frame_title=spec.title,
                )
            except (RuntimeError, OSError, TypeError, ValueError) as exc:
                # Three failure modes routed to the same bucket:
                # - RuntimeError / OSError: socket/transport problems
                #   (broken socket, dead listener) from DisplayClient._send
                # - TypeError / ValueError: encode-side problems from
                #   protocol.encode_message when an element fails to
                #   serialise (e.g. malformed wire shape)
                # All three mean "this frame did not reach the renderer"
                # from the operator's perspective — keep trying later
                # frames so partial coverage on screen is still useful.
                transport_errors.append((spec.frame_id, str(exc)))
                print(
                    f"transport error for frame {spec.frame_id}: {exc}",
                    file=sys.stderr,
                )
                continue
            if ack is None:
                # The display accepted the scene message but no ack returned
                # within the client's recv_timeout (default 5s).
                missed_acks.append(spec.frame_id)
                print(
                    f"Frame {spec.frame_id}: no ack received within 5s "
                    "(display may be stalled, disconnected, or still "
                    "processing the previous scene)",
                    file=sys.stderr,
                )
        return RunResult(
            missed_acks=missed_acks,
            transport_errors=transport_errors,
        )

    # -- frame builders ----------------------------------------------------

    def _build_basics(self) -> FrameSpec:
        """Frame 1 — every static display primitive."""
        elements: list[Element] = [
            TextElement(id="basics-heading", content="Basics", style="heading"),
            TextElement(
                id="basics-body",
                content="Static display primitives — text, image, separator, "
                "progress, spinner, markdown.",
            ),
            SeparatorElement(id="basics-sep1"),
            ImageElement(
                id="basics-image",
                path=str(self._image_path),
                alt="2-stripe pattern (smoke-test asset)",
                width=128,
                height=128,
            ),
            ProgressElement(id="basics-progress", fraction=0.42, label="42%"),
            SpinnerElement(id="basics-spinner", label="loading…", radius=12.0),
            MarkdownElement(
                id="basics-md",
                content=(
                    "## Markdown sample\n\n"
                    "* Bullet one\n"
                    "* Bullet two — **bold** and *italic*\n\n"
                    "Inline `code` and a [link](https://example.com).\n"
                ),
            ),
        ]
        return FrameSpec(
            frame_id="smoke-basics",
            title="Smoke 1 — Basics",
            elements=elements,
            look_for=(
                "heading text, body paragraph, divider, 128px checker image, "
                "42% progress bar, spinning indicator, rendered markdown with "
                "bullets and bold/italic"
            ),
        )

    def _build_inputs(self) -> FrameSpec:
        """Frame 2 — every interactive control."""
        elements: list[Element] = [
            TextElement(id="inputs-heading", content="Inputs", style="heading"),
            ButtonElement(id="inputs-btn", label="Click me", action="clicked"),
            SliderElement(
                id="inputs-slider",
                label="Volume",
                value=42.0,
                min=0.0,
                max=100.0,
            ),
            CheckboxElement(id="inputs-check", label="Enable feature", value=True),
            ComboElement(
                id="inputs-combo",
                label="Mode",
                items=["draft", "review", "published"],
                selected=1,
            ),
            InputTextElement(
                id="inputs-text",
                label="Title",
                value="Hello, Lux",
                hint="enter a title",
            ),
            RadioElement(
                id="inputs-radio",
                label="Severity",
                items=["info", "warn", "error"],
                selected=0,
            ),
            InputNumberElement(
                id="inputs-number",
                label="Threshold",
                value=12.5,
                min=0.0,
                max=100.0,
                step=0.5,
            ),
            ColorPickerElement(
                id="inputs-color",
                label="Accent",
                value="#33CCFF",
                picker=True,
            ),
            SelectableElement(
                id="inputs-select",
                label="Selectable row",
                selected=True,
            ),
        ]
        return FrameSpec(
            frame_id="smoke-inputs",
            title="Smoke 2 — Inputs",
            elements=elements,
            look_for=(
                "clickable button, draggable slider at 42, checked checkbox, "
                "combo dropdown defaulting to 'review', text input pre-filled "
                "with 'Hello, Lux', radio defaulting to 'info', numeric input "
                "with steppers at 12.5, color picker widget showing #33CCFF, "
                "highlighted selectable row"
            ),
        )

    def _build_layout(self) -> FrameSpec:
        """Frame 3 — containers, with nested children to expose containment."""
        group_children: list[Element] = [
            TextElement(id="layout-group-text", content="Children of a rows group"),
            ButtonElement(id="layout-group-btn", label="Nested button"),
            CheckboxElement(
                id="layout-group-check",
                label="Nested checkbox",
                value=False,
            ),
        ]
        header_children: list[Element] = [
            TextElement(
                id="layout-header-text",
                content="Hidden inside a collapsing header (default-open).",
            ),
            SeparatorElement(id="layout-header-sep"),
            ProgressElement(id="layout-header-progress", fraction=0.66),
        ]
        tab_a_children: list[Element] = [
            TextElement(id="layout-tab-a-text", content="Content of tab A."),
            SliderElement(id="layout-tab-a-slider", label="Tab-A slider"),
        ]
        tab_b_children: list[Element] = [
            TextElement(id="layout-tab-b-text", content="Content of tab B."),
            InputTextElement(id="layout-tab-b-text-input", label="Tab-B input"),
        ]
        window_children: list[Element] = [
            TextElement(
                id="layout-window-text",
                content="Children of a movable sub-window.",
            ),
            ButtonElement(id="layout-window-btn", label="Floating button"),
        ]
        elements: list[Element] = [
            TextElement(
                id="layout-heading",
                content="Layout & Containers",
                style="heading",
            ),
            GroupElement(id="layout-group", layout="rows", children=group_children),
            CollapsingHeaderElement(
                id="layout-header",
                label="Disclosure region",
                default_open=True,
                children=header_children,
            ),
            TabBarElement(
                id="layout-tabs",
                tabs=[
                    {"label": "Tab A", "children": tab_a_children},
                    {"label": "Tab B", "children": tab_b_children},
                ],
            ),
            TreeElement(
                id="layout-tree",
                label="Tree root",
                nodes=[
                    {
                        "label": "branch-1",
                        "children": [
                            {"label": "leaf-1a"},
                            {"label": "leaf-1b"},
                        ],
                    },
                    {
                        "label": "branch-2",
                        "children": [{"label": "leaf-2a"}],
                    },
                ],
            ),
            WindowElement(
                id="layout-window",
                title="Sub-window",
                x=80.0,
                y=80.0,
                width=320.0,
                height=180.0,
                children=window_children,
            ),
        ]
        return FrameSpec(
            frame_id="smoke-layout",
            title="Smoke 3 — Layout & Containers",
            elements=elements,
            look_for=(
                "rows-group containing nested children, open collapsing header "
                "with text + separator + progress, tab bar switchable between "
                "A and B, tree with two branches and three leaves, floating "
                "sub-window with its own button"
            ),
        )

    def _build_graphics(self) -> FrameSpec:
        """Frame 4 — DrawElement exercising every draw-command kind."""
        red = Color("#FF5555")
        green = Color("#55FF55")
        blue = Color("#5599FF")
        yellow = Color("#FFCC33")
        white = Color("#FFFFFF")
        stroke = Thickness(2.0)
        caption = "draw commands: line, rect, circle, tri, polyline, bezier, text"
        line = Line(
            p1=Point2(10, 10),
            p2=Point2(110, 60),
            color=red,
            thickness=stroke,
        )
        rect_outline = Rect(
            min=Point2(130, 10),
            max=Point2(230, 60),
            color=green,
            thickness=stroke,
        )
        rect_filled = Rect(
            min=Point2(250, 10),
            max=Point2(350, 60),
            color=blue,
            filled=True,
        )
        circle_outline = Circle(
            center=Point2(60, 130),
            radius=Radius(30.0),
            color=yellow,
            thickness=stroke,
        )
        circle_filled = Circle(
            center=Point2(180, 130),
            radius=Radius(30.0),
            color=red,
            filled=True,
        )
        triangle = Triangle(
            p1=Point2(270, 100),
            p2=Point2(330, 100),
            p3=Point2(300, 160),
            color=green,
            filled=True,
        )
        polyline = Polyline(
            points=(
                Point2(10, 220),
                Point2(40, 200),
                Point2(70, 230),
                Point2(100, 200),
                Point2(130, 230),
            ),
            color=blue,
            thickness=stroke,
        )
        bezier = BezierCubic(
            p1=Point2(170, 220),
            p2=Point2(200, 180),
            p3=Point2(260, 260),
            p4=Point2(310, 220),
            color=yellow,
            thickness=Thickness(2.5),
        )
        glyph = TextGlyph(pos=Point2(10, 280), text=caption, color=white)
        commands = (
            line,
            rect_outline,
            rect_filled,
            circle_outline,
            circle_filled,
            triangle,
            polyline,
            bezier,
            glyph,
        )
        elements: list[Element] = [
            TextElement(
                id="graphics-heading",
                content="Graphics — Draw Commands",
                style="heading",
            ),
            DrawElement(
                id="graphics-canvas",
                width=400,
                height=320,
                bg_color="#202028",
                commands=commands,
            ),
        ]
        return FrameSpec(
            frame_id="smoke-graphics",
            title="Smoke 4 — Graphics",
            elements=elements,
            look_for=(
                "400x320 dark canvas showing all draw-command kinds — red line, "
                "outlined and filled rects, outlined and filled circles, filled "
                "green triangle, blue polyline zigzag, gold bezier S-curve, "
                "caption text along the bottom"
            ),
        )

    def _build_table(self) -> FrameSpec:
        """Frame 5 — TableElement with filters and detail panel."""
        rows: list[list[object]] = [
            ["lux-001", "open", "P0", "Render every element kind"],
            ["lux-002", "in_progress", "P1", "Add manual smoke test"],
            ["lux-003", "closed", "P2", "Document architecture"],
            ["lux-004", "open", "P1", "Decompose display/server.py"],
            ["lux-005", "blocked", "P3", "Texture cache eviction"],
        ]
        detail_rows: list[list[object]] = [
            ["lux-001", "P0", "open"],
            ["lux-002", "P1", "in_progress"],
            ["lux-003", "P2", "closed"],
            ["lux-004", "P1", "open"],
            ["lux-005", "P3", "blocked"],
        ]
        detail_body = [
            "Smoke-test must cover all element kinds across logical frames.",
            "This script is the deliverable for that bead.",
            "Architecture is captured in docs/architecture/system.tex.",
            "server.py and element_renderer.py are still > 1000 lines.",
            "TextureCache currently has no eviction policy — unbounded growth.",
        ]
        table = TableElement(
            id="table-beads",
            columns=["ID", "Status", "Priority", "Title"],
            rows=rows,
            flags=["borders", "row_bg", "resizable", "sortable", "copy_id"],
            filters=[
                TableFilter(
                    type="search",
                    column_spec=3,
                    hint="search titles…",
                    label="Title",
                ),
                TableFilter(
                    type="combo",
                    column_spec=1,
                    items=["All", "open", "in_progress", "closed", "blocked"],
                    label="Status",
                ),
            ],
            detail=TableDetail(
                fields=["ID", "Priority", "Status"],
                rows=detail_rows,
                body=detail_body,
            ),
        )
        elements: list[Element] = [
            TextElement(id="table-heading", content="Table", style="heading"),
            table,
        ]
        return FrameSpec(
            frame_id="smoke-table",
            title="Smoke 5 — Table",
            elements=elements,
            look_for=(
                "5-row table with ID/Status/Priority/Title columns, search "
                "filter on Title, status combo filter ('All', 'open', …), and "
                "a detail panel that updates when a row is selected"
            ),
        )

    def _build_plot(self) -> FrameSpec:
        """Frame 6 — PlotElement with a line and a bar series, labeled axes."""
        line_x = [float(i) for i in range(11)]
        line_y = [float(i * i) / 10.0 for i in range(11)]
        bar_x = [float(i) for i in range(1, 6)]
        bar_y = [3.0, 7.0, 4.0, 9.0, 5.0]
        # PY-TS-14: wire boundary — PlotElement.series is dict-typed in the
        # protocol (each series is a heterogeneous {label, type, x, y} record);
        # tightening it here would require a per-series dataclass that's a
        # downstream concern.
        series: list[dict[str, object]] = [
            {"label": "y = x²/10", "type": "line", "x": line_x, "y": line_y},
            {"label": "samples", "type": "bar", "x": bar_x, "y": bar_y},
        ]
        plot = PlotElement(
            id="plot-demo",
            title="Smoke plot",
            x_label="x (index)",
            y_label="y (value)",
            height=320,
            series=series,
        )
        elements: list[Element] = [
            TextElement(id="plot-heading", content="Plot", style="heading"),
            plot,
        ]
        return FrameSpec(
            frame_id="smoke-plot",
            title="Smoke 6 — Plot",
            elements=elements,
            look_for=(
                "labeled chart with x and y axes, a smooth quadratic line "
                "series ('y = x²/10') and a 5-bar series ('samples') with "
                "values 3, 7, 4, 9, 5"
            ),
        )

    def _build_modal(self) -> FrameSpec:
        """Frame 7 — ModalElement opened by default.

        Lives last so it doesn't trap the operator behind a popup while
        frames 1-6 are still being inspected.  Its containment is exposed
        via two child elements rendered inside the modal body.
        """
        modal_children: list[Element] = [
            TextElement(
                id="modal-text",
                content="This modal is open by default — dismiss with Escape or OK.",
            ),
            ButtonElement(id="modal-btn", label="OK", action="dismiss"),
        ]
        elements: list[Element] = [
            TextElement(id="modal-heading", content="Modal", style="heading"),
            TextElement(
                id="modal-intro",
                content=(
                    "The modal popup appears over this frame.  Dismiss it to "
                    "interact with the rest of the display."
                ),
            ),
            ModalElement(
                id="modal-dialog",
                title="Modal dialog",
                open=True,
                children=modal_children,
            ),
        ]
        return FrameSpec(
            frame_id="smoke-modal",
            title="Smoke 7 — Modal",
            elements=elements,
            look_for=(
                "popup labelled 'Modal dialog' over the frame, containing text "
                "and an OK button; dismissing with Escape or OK returns "
                "interaction to the underlying display"
            ),
            warn_before_send=(
                "Frame 7 opens a modal — dismiss with Escape or click OK "
                "before inspecting other frames."
            ),
        )


# ---------------------------------------------------------------------------
# Main driver.
# ---------------------------------------------------------------------------


def main() -> int:
    """Send every frame, print the manifest, exit per the docstring table.

    Sanity-checks that the union of every frame's kinds matches the
    24-kind expected set before contacting the display — a missing kind
    fails loud with a diff before any I/O happens.

    Connect failures (display not running, socket refused) are surfaced
    as the documented exit-2 transport failure with a clear stderr
    message, never as an unframed traceback.  ``auto_spawn`` is left
    off so the script fails the prerequisite check loudly rather than
    silently spawning a display the operator didn't ask for.
    """
    image_path = _write_sample_png()
    runner = SmokeRunner(image_path)
    coverage_error = runner.verify_coverage()
    if coverage_error is not None:
        # The manifest is the operator's cross-reference even when nothing
        # was sent — print it before exiting so they can see what the script
        # would have rendered if the coverage check had passed.
        print(coverage_error, file=sys.stderr)
        runner.print_manifest(attempted=False)
        return 5
    try:
        client = DisplayClient(name="manual-smoke", auto_spawn=False)
        client.connect()
    except (RuntimeError, OSError) as exc:
        # DisplayClient.connect() raises RuntimeError when the display
        # isn't accepting connections (no socket, refused handshake,
        # protocol mismatch).  Document it as a transport failure so the
        # operator sees exit 2 with a clear reason instead of a traceback.
        print(
            f"connect failed: {exc} (is luxd + lux-display running?)",
            file=sys.stderr,
        )
        runner.print_manifest(attempted=False)
        return 2
    try:
        result = runner.run(client)
    finally:
        client.close()
        runner.print_manifest(attempted=True)
    if result.missed_acks:
        print(
            f"smoke ack-timeout: {len(result.missed_acks)} of "
            f"{len(runner.frames)} frames had no ack "
            f"({', '.join(result.missed_acks)})",
            file=sys.stderr,
        )
    if result.transport_errors:
        ids = ", ".join(fid for fid, _ in result.transport_errors)
        print(
            f"smoke transport-error: {len(result.transport_errors)} of "
            f"{len(runner.frames)} frames failed to send ({ids})",
            file=sys.stderr,
        )
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
