"""Programmer Calculator — multi-base integer calculator in a Lux frame.

Render-function-based applet for the Applications menu.  Supports
arithmetic, bitwise operations, and multi-base display (Dec/Hex/Bin/Oct)
with toggleable bit grid.

Public API:
    CALCULATOR_SOURCE  — render function source string
    render_calculator  — send the calculator to a LuxClient
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.protocol import RenderFunctionElement

if TYPE_CHECKING:
    from punt_lux.client import LuxClient

CALCULATOR_SOURCE = """\
def render(ctx):
    from imgui_bundle import imgui

    s = ctx.state
    if "display" not in s:
        s["display"] = "0"
        s["accumulator"] = 0
        s["operator"] = None
        s["new_input"] = True
        s["history"] = []
        s["bit_width"] = 32
        s["base"] = 10

    bit_width = s["bit_width"]
    mask = (1 << bit_width) - 1

    def cur_val():
        try:
            return int(s["display"]) & mask
        except ValueError:
            return 0

    def set_display(v):
        v = int(v) & mask
        s["display"] = str(v)

    def format_val(v, base):
        v = int(v) & mask
        if base == 16:
            return hex(v).upper().replace("0X", "0x")
        if base == 2:
            return bin(v)
        if base == 8:
            return oct(v)
        return str(v)

    # --- multi-base display ---
    v = cur_val()
    bases = [("Dec", 10), ("Hex", 16), ("Bin", 2), ("Oct", 8)]
    for label, b in bases:
        imgui.text(f"{label}: {format_val(v, b)}")

    imgui.separator()

    # --- bit grid ---
    bits = bit_width
    cols = min(bits, 16)
    for row_start in range(bits - 1, -1, -cols):
        for i in range(row_start, max(row_start - cols, -1), -1):
            bit_set = bool(v & (1 << i))
            label = f"{int(bit_set)}##{i}"
            if bit_set:
                btn_color = imgui.ImVec4(0.2, 0.5, 0.8, 1.0)
                imgui.push_style_color(
                    imgui.Col_.button.value, btn_color,
                )
            if imgui.button(label, imgui.ImVec2(18, 18)):
                v ^= (1 << i)
                set_display(v)
            if bit_set:
                imgui.pop_style_color()
            if i > row_start - cols + 1:
                imgui.same_line()
        # bit index labels
        idx_range = range(row_start, max(row_start - cols, -1), -1)
        idx_text = "  ".join(f"{i:>2}" for i in idx_range)
        dim = imgui.ImVec4(0.5, 0.5, 0.5, 1.0)
        imgui.text_colored(dim, idx_text)

    imgui.separator()

    # --- bit width selector ---
    for bw in [8, 16, 32, 64]:
        if bw != 8:
            imgui.same_line()
        selected = (s["bit_width"] == bw)
        if selected:
            sel_color = imgui.ImVec4(0.3, 0.6, 0.3, 1.0)
            imgui.push_style_color(
                imgui.Col_.button.value, sel_color,
            )
        if imgui.button(f"{bw}-bit"):
            s["bit_width"] = bw
            set_display(cur_val())
        if selected:
            imgui.pop_style_color()

    imgui.separator()

    # --- quick values ---
    quick = [("255", 255), ("1K", 1024), ("64K", 65536), ("MAX", mask)]
    for i, (ql, qv) in enumerate(quick):
        if i > 0:
            imgui.same_line()
        if imgui.button(ql):
            set_display(qv)
            s["new_input"] = True

    imgui.separator()

    # --- button grid ---
    def do_op():
        acc = s["accumulator"]
        op = s["operator"]
        val = cur_val()
        if op == "+":
            return acc + val
        if op == "-":
            return acc - val
        if op == "*":
            return acc * val
        if op == "/":
            return acc // val if val != 0 else 0
        if op == "%":
            return acc % val if val != 0 else 0
        if op == "&":
            return acc & val
        if op == "|":
            return acc | val
        if op == "^":
            return acc ^ val
        if op == "<<":
            return acc << (val & 63)
        if op == ">>":
            return acc >> (val & 63)
        return val

    btn_w = imgui.ImVec2(40, 28)
    rows = [
        ["7", "8", "9", "/"],
        ["4", "5", "6", "*"],
        ["1", "2", "3", "-"],
        ["0", "C", "=", "+"],
    ]
    for row in rows:
        for j, b in enumerate(row):
            if j > 0:
                imgui.same_line()
            if imgui.button(b, btn_w):
                if b.isdigit():
                    if s["new_input"]:
                        s["display"] = b
                        s["new_input"] = False
                    else:
                        s["display"] = s["display"] + b
                elif b == "C":
                    s["display"] = "0"
                    s["accumulator"] = 0
                    s["operator"] = None
                    s["new_input"] = True
                elif b == "=":
                    if s["operator"] is not None:
                        acc = s["accumulator"]
                        op = s["operator"]
                        expr = f"{acc} {op} {cur_val()}"
                        result = do_op()
                        set_display(result)
                        masked = int(result) & mask
                        s["history"].append(
                            f"{expr} = {masked}",
                        )
                        s["operator"] = None
                        s["new_input"] = True
                else:
                    if s["operator"] is not None:
                        result = do_op()
                        set_display(result)
                        s["accumulator"] = result & mask
                    else:
                        s["accumulator"] = cur_val()
                    s["operator"] = b
                    s["new_input"] = True

    # --- bitwise ops row ---
    bit_ops = ["&", "|", "^", "~", "<<", ">>"]
    for i, op in enumerate(bit_ops):
        if i > 0:
            imgui.same_line()
        if imgui.button(op, imgui.ImVec2(32, 28)):
            if op == "~":
                set_display(~cur_val())
                s["new_input"] = True
            else:
                if s["operator"] is not None:
                    result = do_op()
                    set_display(result)
                    s["accumulator"] = result & mask
                else:
                    s["accumulator"] = cur_val()
                s["operator"] = op
                s["new_input"] = True

    # --- history ---
    if s["history"]:
        imgui.separator()
        imgui.text_colored(imgui.ImVec4(0.5, 0.5, 0.5, 1.0), "History:")
        for h in s["history"][-5:]:
            imgui.text(h)
"""


def render_calculator(client: LuxClient) -> None:
    """Send the programmer calculator to the display via *client*.

    Uses ``show_async`` so the call is non-blocking (safe to call from
    a menu callback thread).
    """
    client.show_async(
        "app-calculator",
        elements=[
            RenderFunctionElement(id="calc", source=CALCULATOR_SOURCE),
        ],
        frame_id="app-calculator",
        frame_title="Calculator",
        frame_size=(350, 500),
    )
