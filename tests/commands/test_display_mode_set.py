"""Direct tests for :class:`DisplayModeSetCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

import pytest

from punt_lux.commands import Ctx, DisplayModeOps, display_mode_set
from punt_lux.operations import DisplayModeRequest, OpError
from tests.commands._family_stubs import StubDisplayModeOps
from tests.commands._scene_stub import identity


def _request(mode: str = "y", repo: str = "/repo") -> DisplayModeRequest | OpError:
    return DisplayModeRequest.parse(mode, repo)


def test_op_error_raises_value_error_on_malformed_input() -> None:
    """A ``DisplayModeRequest.parse`` failure round-trips as ``ValueError``."""
    ops = StubDisplayModeOps(write_result=OpError(code="invalid_request", reason="bad"))
    ctx: Ctx[DisplayModeOps] = Ctx(ops=ops, identity=identity())

    with pytest.raises(ValueError, match="bad"):
        asyncio.run(display_mode_set(ctx, _request(mode="oops")))


def test_routes_request_through_to_ops() -> None:
    request = _request()
    ops = StubDisplayModeOps(
        write_result=OpError(code="fault", reason="pin routing arg"),
    )
    ctx: Ctx[DisplayModeOps] = Ctx(ops=ops, identity=identity())

    with pytest.raises(ValueError, match="pin routing arg"):
        asyncio.run(display_mode_set(ctx, request))

    assert ops.last_call == {"method": "write_display_mode", "request": request}
