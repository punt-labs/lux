"""DrawElementRenderer — color parsing and real-signature replay guard.

``_parse_color`` normalizes every color spelling the wire may carry to an
``(r, g, b, a)`` tuple, falling back to opaque white on anything malformed.

The replay methods call ``ImDrawList.add_*``; a ``MagicMock`` draw list accepts
any arguments, so an argument-order or keyword mismatch renders green in tests
while crashing the live display. ``_RealSignatureDrawList`` closes that gap: it
parses each ``add_*`` signature from the installed imgui-bundle binding and
rejects a call that binds a value into the wrong-typed slot (a float where an
int ``flags`` goes — the exact defect that crashed a valid rect). Reading the
binding's signatures needs no GPU.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Self
from unittest.mock import MagicMock

import pytest
from imgui_bundle import imgui

from punt_lux.display.renderers.draw_element_renderer import DrawElementRenderer
from punt_lux.protocol.elements.draw import DrawElement


class TestParseColor:
    def test_hex_rgb(self) -> None:
        assert DrawElementRenderer._parse_color("#FF8000") == (255, 128, 0, 255)

    def test_hex_rgba(self) -> None:
        assert DrawElementRenderer._parse_color("#FF800080") == (255, 128, 0, 128)

    def test_hex_no_hash(self) -> None:
        assert DrawElementRenderer._parse_color("FF8000") == (255, 128, 0, 255)

    def test_list_rgb(self) -> None:
        assert DrawElementRenderer._parse_color([70, 130, 230]) == (70, 130, 230, 255)

    def test_list_rgba(self) -> None:
        assert DrawElementRenderer._parse_color([70, 130, 230, 128]) == (
            70,
            130,
            230,
            128,
        )

    def test_tuple_rgba(self) -> None:
        assert DrawElementRenderer._parse_color((200, 80, 60, 255)) == (
            200,
            80,
            60,
            255,
        )

    def test_invalid_hex_falls_back_to_white(self) -> None:
        assert DrawElementRenderer._parse_color("#ZZZZZZ") == (255, 255, 255, 255)

    def test_invalid_type_falls_back_to_white(self) -> None:
        assert DrawElementRenderer._parse_color(object()) == (255, 255, 255, 255)


# -- real-signature replay guard --------------------------------------------


def _parse_params(fn: object) -> list[tuple[str, str]]:
    """Parse ``[(name, annotation)]`` from a nanobind method's doc signature.

    ``inspect.signature`` raises on nanobind bindings, so read the first doc
    line: ``add_rect(self, p_min: T, ..., flags: int = 0) -> None``. None of the
    real ImDrawList annotations contain a comma, so a plain split is safe here.
    """
    doc = (fn.__doc__ or "").splitlines()[0]
    inner = doc[doc.index("(") + 1 : doc.rindex(") ->")]
    params: list[tuple[str, str]] = []
    for raw in inner.split(","):
        part = raw.strip()
        if not part:
            continue
        name = part.split(":")[0].split("=")[0].strip()
        annotation = part.split(":", 1)[1].split("=")[0].strip() if ":" in part else ""
        params.append((name, annotation))
    return params


class _RealSignatureDrawList:
    """A draw-list double that validates each add_* call against the real binding.

    It binds the call's positional and keyword arguments to the parameters parsed
    from the installed imgui-bundle signature, rejecting an unknown keyword name
    (a renamed parameter) and a float bound to an ``int`` slot (the flags-gets-a-
    thickness-float crash). Any non-add_* call (clip-rect) is a no-op — not the
    audited surface.
    """

    _params: dict[str, list[tuple[str, str]]]
    __slots__ = ("_params",)

    _ADD = (
        "add_line",
        "add_rect",
        "add_rect_filled",
        "add_circle",
        "add_circle_filled",
        "add_triangle",
        "add_triangle_filled",
        "add_text",
        "add_polyline",
        "add_bezier_cubic",
    )

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._params = {
            name: _parse_params(getattr(imgui.ImDrawList, name)) for name in cls._ADD
        }
        return self

    def __getattr__(self, name: str) -> Callable[..., None]:
        if name.startswith("__"):
            raise AttributeError(name)
        if name in type(self)._ADD:
            return lambda *args, **kwargs: self._validate(name, args, kwargs)
        return lambda *args, **kwargs: None

    def _validate(
        self, name: str, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> None:
        # params[0] is 'self'; the bound-method call omits it, so match args to
        # the remaining parameters in order.
        real = self._params[name][1:]
        if len(args) > len(real):
            msg = f"{name}: {len(args)} positional args, signature has {len(real)}"
            raise TypeError(msg)
        bound: dict[str, tuple[object, str]] = {
            pname: (value, ann) for value, (pname, ann) in zip(args, real, strict=False)
        }
        valid = {pname for pname, _ in real}
        for key, value in kwargs.items():
            if key not in valid:
                msg = f"{name}: no parameter named {key!r} in {sorted(valid)}"
                raise TypeError(msg)
            bound[key] = (value, next(ann for pname, ann in real if pname == key))
        for pname, (value, ann) in bound.items():
            if ann != "int":
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                got = type(value).__name__
                msg = f"{name}: parameter {pname!r} expects int, got {got}"
                raise TypeError(msg)


_ALL_COMMANDS: list[dict[str, object]] = [
    {"cmd": "line", "p1": [0, 0], "p2": [10, 5], "thickness": 2},
    {"cmd": "rect", "min": [0, 0], "max": [10, 10], "rounding": 2, "thickness": 2},
    {"cmd": "rect", "min": [0, 0], "max": [10, 10], "filled": True},
    {"cmd": "circle", "center": [5, 5], "radius": 3, "thickness": 2},
    {"cmd": "circle", "center": [5, 5], "radius": 3, "filled": True},
    {"cmd": "triangle", "p1": [0, 0], "p2": [1, 0], "p3": [0, 1], "thickness": 2},
    {"cmd": "triangle", "p1": [0, 0], "p2": [1, 0], "p3": [0, 1], "filled": True},
    {"cmd": "text", "pos": [5, 5], "text": "hi"},
    {"cmd": "polyline", "points": [[0, 0], [1, 1], [2, 0]], "closed": True},
    {"cmd": "bezier_cubic", "p1": [0, 0], "p2": [1, 0], "p3": [2, 1], "p4": [3, 1]},
]


def _fake_imgui(draw_list: _RealSignatureDrawList) -> MagicMock:
    fake = MagicMock()
    fake.get_window_draw_list.return_value = draw_list
    fake.get_color_u32.return_value = 0xFF3366FF  # a real packed-color int for `col`
    pos = MagicMock()
    pos.x = 0.0
    pos.y = 0.0
    fake.get_cursor_screen_pos.return_value = pos
    return fake


def test_replay_matches_the_real_imdrawlist_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every command's add_* call binds cleanly to the installed signature."""
    element = DrawElement.from_dict(
        {"kind": "draw", "id": "dr1", "bg_color": "#101010", "commands": _ALL_COMMANDS}
    )
    draw_list = _RealSignatureDrawList()
    monkeypatch.setattr(
        "punt_lux.display.renderers.draw_element_renderer.imgui",
        _fake_imgui(draw_list),
    )
    DrawElementRenderer().render(element)  # raises TypeError on any mismatch


def test_the_guard_reproduces_the_flags_slot_defect() -> None:
    """The old positional add_rect — flags receiving a thickness float — is caught."""
    draw_list = _RealSignatureDrawList()
    vec = imgui.ImVec2(0.0, 0.0)
    with pytest.raises(TypeError, match="flags"):
        # (p_min, p_max, col, rounding, thickness, flags) with flags = 2.0 (float)
        draw_list.add_rect(vec, vec, 0xFF0000FF, 2.0, 0, 2.0)
