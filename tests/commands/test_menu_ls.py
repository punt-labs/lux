"""Direct tests for :class:`MenuLsCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, MenuOps, menu_ls
from punt_lux.operations import MenuList
from tests.commands._family_stubs import StubMenuOps
from tests.commands._scene_stub import identity


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    menus = MenuList(menus=[])
    ops = StubMenuOps(list_result=menus)
    ctx: Ctx[MenuOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(menu_ls.execute(ctx))

    assert result == menus


def test_call_renders_menu_count_into_the_shared_envelope() -> None:
    ops = StubMenuOps(list_result=MenuList(menus=[]))
    ctx: Ctx[MenuOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(menu_ls(ctx))

    assert result.text == "menus:0"
    assert result.error is False


def test_routes_the_zero_arg_call_through_to_list_menus() -> None:
    ops = StubMenuOps(list_result=MenuList(menus=[]))
    ctx: Ctx[MenuOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(menu_ls.execute(ctx))

    assert ops.last_call == {"method": "list_menus"}
