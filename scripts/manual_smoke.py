"""Manual smoke test — render every supported element kind across 8 frames.

Invoked as:

    uv run --extra display python scripts/manual_smoke.py

Requires luxd + lux-display already running.  Will NOT auto-spawn —
the script fails loudly (exit 2) when the prerequisite isn't met
because silent auto-spawn would hide the operator setup mistake the
script is meant to surface.

Submits through the front door — :class:`LuxRestClient` builds a
:class:`RenderRequest` per frame, exactly as the CLI and the beads
board do (``lux show beads``, ``BeadsBoardCommand``). Every frame
therefore exercises the real Hub path (decode, self-validate, install,
replicate) and not just the display's renderer; a malformed element
is caught by Hub-side validation instead of skirting it over a raw
socket.

Sends 8 themed scenes — basics, inputs, layout, graphics, table, plot,
modal, dialog — and prints a cross-reference manifest to stdout that
names each frame's contents and what the operator should look for.
Does NOT clear any scene — items stay on screen for visual inspection.

Exit codes:

* ``0`` — every frame's render request was accepted
* ``1`` — at least one frame was rejected by the Hub (``OpError`` —
  e.g. a validation failure), with no transport failure
* ``2`` — luxd or the display was unreachable for at least one frame:
  the initial connect/ping precondition failed, a request raised
  ``HubUnavailableError``, or a frame's elements failed to encode to
  their wire dict before the request could be sent
* ``3`` — both a Hub rejection AND a transport failure occurred
* ``4`` — PNG asset preparation failed before the display was contacted
* ``5`` — element-kind coverage mismatch — the union of every frame's
  kinds did not match the 25-kind expected set; a frame builder dropped
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
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Self, cast

from PIL import Image, UnidentifiedImageError

from punt_lux.domain.validation_walk import HasChildElements
from punt_lux.operations import OpError, RenderRequest
from punt_lux.operations.models.render import FrameSpec
from punt_lux.protocol import Element
from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    DialogElement,
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
    Tab,
    TabBarElement,
    TableElement,
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
from punt_lux.protocol.elements.plot_series import PlotSeries
from punt_lux.protocol.elements.table_flags import TableFlags
from punt_lux.protocol.elements.tree_node import TreeNode
from punt_lux.protocol.elements.window_chrome import WindowPlacement
from punt_lux.rest_client import LuxRestClient
from punt_lux.rest_transport import HubUnavailableError


@dataclass(frozen=True, slots=True)
class SmokeFrame:
    """One frame in the smoke test — the scene plus its manifest entry.

    ``elements`` is the source of truth for what's on screen and drives
    :func:`_collect_kinds` for the coverage manifest.  ``kinds`` is *not*
    stored, so a stale hardcoded tuple can't lie about what the frame
    actually contains.  ``look_for`` is narrative for the operator and
    stays hardcoded.

    ``wire_override``, when set, is what actually gets sent instead of
    ``[e.to_dict() for e in elements]``. A structural encoder writes only
    an element's shape, not the handler bindings that make its children
    do anything — ``DialogElement.to_dict()`` documents this outright —
    so a frame whose interactivity depends on those bindings supplies the
    real wire dict here, the same shape an agent would author by hand.
    ``elements`` still carries a decoded twin for the coverage walk.
    """

    frame_id: str
    title: str
    elements: list[Element]
    look_for: str
    warn_before_send: str | None = None  # PY-TS-14: absent = no operator warning
    wire_override: list[dict[str, object]] | None = None  # PY-TS-14: see docstring


@dataclass(frozen=True, slots=True)
class RunResult:
    """Result of a :meth:`SmokeRunner.run` call.

    ``rejected`` are frame ids paired with the reason the Hub gave for
    refusing the request (an ``OpError`` — e.g. a validation failure).
    ``transport_errors`` are frame ids paired with the message from a
    failure that meant the request never reached the Hub at all — a
    ``HubUnavailableError`` (luxd unreachable or stalled) or a local
    encode failure building the wire dict.
    """

    rejected: list[tuple[str, str]] = field(default_factory=list)
    transport_errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """Return the 2-bit OR of rejections (1) and transport-errors (2)."""
        code = 0
        if self.rejected:
            code |= 1
        if self.transport_errors:
            code |= 2
        return code


# The 25 known element kinds covered by this smoke test.  Used for the
# top-of-main sanity assertion — if a frame builder loses an element kind,
# the assertion fires before the display is contacted.
_EXPECTED_KINDS: Final = frozenset(
    {
        "button",
        "checkbox",
        "collapsing_header",
        "color_picker",
        "combo",
        "dialog",
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
# stateless, no SmokeFrame/SmokeRunner vocabulary.
# ---------------------------------------------------------------------------


def _collect_kinds(elements: Iterable[Element]) -> frozenset[str]:
    """Walk every element and its container children, returning the set of kinds.

    A container exposes its children through the ``HasChildElements`` protocol
    (``child_elements()``): a group/header/window/modal/dialog returns its
    children, a tab_bar flattens every tab's children. A tree's nodes are a
    typed value family carrying no element kinds, so it contributes only
    ``"tree"``. ``DrawElement.commands`` likewise contribute only ``"draw"``.
    """
    kinds: set[str] = set()
    for elem in elements:
        kinds.add(elem.kind)
        if isinstance(elem, HasChildElements):
            kinds |= _collect_kinds(cast("Iterable[Element]", elem.child_elements()))
    return frozenset(kinds)


# ---------------------------------------------------------------------------
# PNG asset generation — primitives toolkit, PY-OO-7 exception:
# stateless, no SmokeFrame/SmokeRunner vocabulary.  We hand-roll a tiny PNG
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
    """Build the eight smoke-test frames, verify coverage, drive the send loop.

    Frame builders are methods that share the runner's vocabulary
    (every one returns a :class:`SmokeFrame`).  The previous module-level
    helpers were a PY-OO-7 smell: a class plus a cluster of free
    functions all producing instances of the class.  Now each is a
    method; the runner is the single seam between the test data and
    the display.
    """

    _image_path: Path
    _frames: list[SmokeFrame]

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
            self._build_dialog(),
        ]
        return self

    # -- public surface ----------------------------------------------------

    @property
    def frames(self) -> list[SmokeFrame]:
        """Return the eight SmokeFrames in send order (modal, then dialog, last)."""
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
        no frame ever reached ``client.render()`` (connect failed, coverage
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

    def run(self, client: LuxRestClient) -> RunResult:
        """Send every frame through the front door, return a :class:`RunResult`.

        Tries every frame even if earlier ones fail — partial coverage
        on screen is more useful than a clean abort.  ``warn_before_send``
        prints to stderr before the corresponding frame is dispatched so
        the operator knows e.g. a modal is about to take over.

        Each frame becomes its own :class:`RenderRequest`, exactly as an
        agent or the CLI would build one — the Hub decodes and self-validates
        the elements on receipt, so this exercises the real install path,
        not just the wire encode.

        Accumulates failures into local lists and constructs the
        ``RunResult`` once at the end.  Mutating ``frozen=True``
        instance fields (even mutable lists) breaks the frozen
        contract — callers see a dataclass whose lists are still being
        populated under the rug.
        """
        rejected: list[tuple[str, str]] = []
        transport_errors: list[tuple[str, str]] = []
        for spec in self._frames:
            if spec.warn_before_send is not None:
                print(spec.warn_before_send, file=sys.stderr)
            try:
                payload = spec.wire_override or [
                    elem.to_dict() for elem in spec.elements
                ]
                request = RenderRequest(
                    scene_id=spec.frame_id,
                    elements=payload,
                    title=spec.title,
                    frame=FrameSpec(frame_id=spec.frame_id, frame_title=spec.title),
                )
                result = client.render(request)
            except (HubUnavailableError, TypeError, ValueError) as exc:
                # Three failure modes routed to the same bucket, all meaning
                # "this frame did not reach the renderer" from the operator's
                # perspective:
                # - HubUnavailableError: luxd is unreachable or stalled
                #   (LuxRestClient._send / the loopback transport)
                # - TypeError / ValueError: a local encode-side failure
                #   building the wire dict (element.to_dict()) before any
                #   request was sent
                transport_errors.append((spec.frame_id, str(exc)))
                print(
                    f"transport error for frame {spec.frame_id}: {exc}",
                    file=sys.stderr,
                )
                continue
            if isinstance(result, OpError):
                # The request reached the Hub, which decoded and rejected it
                # — a real validation failure, not a transport problem.
                rejected.append((spec.frame_id, result.reason))
                print(
                    f"Frame {spec.frame_id} rejected: {result.reason}",
                    file=sys.stderr,
                )
        return RunResult(rejected=rejected, transport_errors=transport_errors)

    # -- frame builders ----------------------------------------------------

    def _build_basics(self) -> SmokeFrame:
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
        return SmokeFrame(
            frame_id="smoke-basics",
            title="Smoke 1 — Basics",
            elements=elements,
            look_for=(
                "heading text, body paragraph, divider, 128px checker image, "
                "42% progress bar, spinning indicator, rendered markdown with "
                "bullets and bold/italic"
            ),
        )

    def _build_inputs(self) -> SmokeFrame:
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
        return SmokeFrame(
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

    def _build_layout(self) -> SmokeFrame:
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
                open=True,
                children=header_children,
            ),
            TabBarElement(
                id="layout-tabs",
                tabs=(
                    Tab(tab_id="tab-a", label="Tab A", children=tuple(tab_a_children)),
                    Tab(tab_id="tab-b", label="Tab B", children=tuple(tab_b_children)),
                ),
                active_tab="tab-a",
            ),
            TreeElement(
                id="layout-tree",
                label="Tree root",
                nodes=(
                    TreeNode(
                        label="branch-1",
                        children=(
                            TreeNode(label="leaf-1a"),
                            TreeNode(label="leaf-1b"),
                        ),
                    ),
                    TreeNode(label="branch-2", children=(TreeNode(label="leaf-2a"),)),
                ),
            ),
            WindowElement(
                id="layout-window",
                title="Sub-window",
                placement=WindowPlacement(x=80.0, y=80.0, width=320.0, height=180.0),
                children=window_children,
            ),
        ]
        return SmokeFrame(
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

    def _build_graphics(self) -> SmokeFrame:
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
        return SmokeFrame(
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

    def _build_table(self) -> SmokeFrame:
        """Frame 5 — the basic data grid (single-select, real column sort)."""
        rows: tuple[tuple[object, ...], ...] = (
            ("lux-001", "open", "P0", "Render every element kind"),
            ("lux-002", "in_progress", "P1", "Add manual smoke test"),
            ("lux-003", "closed", "P2", "Document architecture"),
            ("lux-004", "open", "P1", "Decompose display/render_loop.py"),
            ("lux-005", "blocked", "P3", "Texture cache eviction"),
        )
        table = TableElement(
            id="table-beads",
            columns=("ID", "Status", "Priority", "Title"),
            rows=rows,
            flags=TableFlags(
                borders=True, row_bg=True, resizable=True, sortable=True, copy_id=True
            ),
            key_column=0,
            selection_mode="single",
        )
        elements: list[Element] = [
            TextElement(id="table-heading", content="Table", style="heading"),
            table,
        ]
        return SmokeFrame(
            frame_id="smoke-table",
            title="Smoke 5 — Table",
            elements=elements,
            look_for=(
                "5-row grid with ID/Status/Priority/Title columns; clicking a "
                "row selects it, and clicking a column header sorts the rows"
            ),
        )

    def _build_plot(self) -> SmokeFrame:
        """Frame 6 — PlotElement with a line and a bar series, labeled axes."""
        line_x = tuple(float(i) for i in range(11))
        line_y = tuple(float(i * i) / 10.0 for i in range(11))
        bar_x = tuple(float(i) for i in range(1, 6))
        bar_y = (3.0, 7.0, 4.0, 9.0, 5.0)
        series = (
            PlotSeries("y = x²/10", "line", line_x, line_y),
            PlotSeries("samples", "bar", bar_x, bar_y),
        )
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
        return SmokeFrame(
            frame_id="smoke-plot",
            title="Smoke 6 — Plot",
            elements=elements,
            look_for=(
                "labeled chart with x and y axes, a smooth quadratic line "
                "series ('y = x²/10') and a 5-bar series ('samples') with "
                "values 3, 7, 4, 9, 5"
            ),
        )

    def _build_modal(self) -> SmokeFrame:
        """Frame 7 — ModalElement opened by default.

        Lives after the primary frames so it doesn't trap the operator
        behind a popup while frames 1-6 are still being inspected. Its
        containment is exposed via two child elements rendered inside
        the modal body.

        The OK button carries no handler — no ``ButtonHandlers`` factory
        closes a modal from a child click today, only the display's own
        Escape/X path fires ``ModalClosed``. The button demonstrates a
        plain child inside the modal body; it does not claim to dismiss.
        """
        modal_dialog = ModalElement(id="modal-dialog", title="Modal dialog", open=True)
        # The ABC modal receives its body through the decoder seam, not the
        # constructor; installing here mirrors what the wire decoder does.
        modal_dialog.install_children(
            (
                TextElement(
                    id="modal-text",
                    content="This modal is open by default — dismiss with Escape.",
                ),
                ButtonElement(id="modal-btn", label="OK"),
            )
        )
        elements: list[Element] = [
            TextElement(id="modal-heading", content="Modal", style="heading"),
            TextElement(
                id="modal-intro",
                content=(
                    "The modal popup appears over this frame.  Dismiss it to "
                    "interact with the rest of the display."
                ),
            ),
            modal_dialog,
        ]
        return SmokeFrame(
            frame_id="smoke-modal",
            title="Smoke 7 — Modal",
            elements=elements,
            look_for=(
                "popup labelled 'Modal dialog' over the frame, containing text "
                "and an OK button (unwired — a plain child, not a dismiss "
                "control); dismissing with Escape returns interaction to the "
                "underlying display"
            ),
            warn_before_send=(
                "Frame 7 opens a modal — dismiss with Escape before "
                "inspecting other frames."
            ),
        )

    def _build_dialog(self) -> SmokeFrame:
        """Frame 8 — DialogElement, the MVC composite with model-bound buttons.

        Lives last, after the modal, for the same reason the modal isn't
        first: an open overlay must not trap the operator away from
        frames 1-6. A dialog is its own kind, distinct from a modal.

        ``DialogElement.to_dict()`` writes only the structural surface —
        id, title, child kinds — never the handler specs that bind a
        child Button to the dialog's ``confirm``/``cancel`` verbs (its
        own encoder docstring says so). A Python-built dialog therefore
        cannot round-trip into a working one through the generic encode
        path; the wire dict below is hand-authored the way an agent
        would write it, matching the shape the Hub's ``call_model``
        button decoder actually requires (``handlers: [{"event": "click",
        "factory": "call_model", "verb": ...}]``). ``elements`` still
        carries a *decoded* twin (``DialogElement.from_dict`` on the same
        dict) purely so the coverage walk can report kinds; the frame is
        sent via ``wire_override``, not ``elements``.
        """
        dialog_wire: dict[str, object] = {
            "kind": "dialog",
            "id": "dialog-confirm",
            "title": "Confirm action",
            "children": [
                {
                    "kind": "button",
                    "id": "dialog-cancel",
                    "label": "Cancel",
                    "handlers": [
                        {"event": "click", "factory": "call_model", "verb": "cancel"},
                    ],
                },
                {
                    "kind": "button",
                    "id": "dialog-confirm-btn",
                    "label": "Confirm",
                    "handlers": [
                        {"event": "click", "factory": "call_model", "verb": "confirm"},
                    ],
                },
            ],
        }
        heading = TextElement(id="dialog-heading", content="Dialog", style="heading")
        intro = TextElement(
            id="dialog-intro",
            content=(
                "The dialog popup appears over this frame, with Cancel and "
                "Confirm buttons bound to the dialog's model."
            ),
        )
        dialog = DialogElement.from_dict(dialog_wire)
        return SmokeFrame(
            frame_id="smoke-dialog",
            title="Smoke 8 — Dialog",
            elements=[heading, intro, dialog],
            look_for=(
                "popup labelled 'Confirm action' over the frame, with Cancel "
                "and Confirm buttons; dismissing either returns interaction "
                "to the underlying display"
            ),
            warn_before_send=(
                "Frame 8 opens a dialog — dismiss with Cancel or Confirm "
                "before inspecting other frames."
            ),
            wire_override=[heading.to_dict(), intro.to_dict(), dialog_wire],
        )


# ---------------------------------------------------------------------------
# Main driver.
# ---------------------------------------------------------------------------


def main() -> int:
    """Send every frame, print the manifest, exit per the docstring table.

    Sanity-checks that the union of every frame's kinds matches the
    25-kind expected set before contacting the display — a missing kind
    fails loud with a diff before any I/O happens.

    Connects and pings through the same front door an agent or the CLI
    uses (:class:`LuxRestClient`) — ``ping()`` proves the Hub actually
    holds a live Display connection, not just that luxd's port file
    exists. Prerequisite failures are surfaced as the documented exit-2
    failure with a clear stderr message, never as an unframed traceback.
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
        client = LuxRestClient.connect()
        ping_result = client.ping()
    except HubUnavailableError as exc:
        # connect() only checks that the port file exists; ping() is the
        # first real HTTP round-trip, and a stale port file or a dead luxd
        # raises here just as readily as at connect() — same bucket, same
        # exit code.
        print(f"connect failed: {exc}", file=sys.stderr)
        runner.print_manifest(attempted=False)
        return 2
    if isinstance(ping_result, OpError):
        print(
            f"display not reachable: {ping_result.reason} (is lux-display running?)",
            file=sys.stderr,
        )
        runner.print_manifest(attempted=False)
        return 2
    result = runner.run(client)
    runner.print_manifest(attempted=True)
    if result.rejected:
        print(
            f"smoke rejected: {len(result.rejected)} of "
            f"{len(runner.frames)} frames were rejected by the Hub "
            f"({', '.join(fid for fid, _ in result.rejected)})",
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
