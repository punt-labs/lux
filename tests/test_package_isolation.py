"""Library and lifecycle imports never initialize the Lux engine or renderers."""

from __future__ import annotations

import pytest

from tests.fresh_imports import (
    assert_importable,
    assert_isolated,
    assert_not_importable,
    package_modules,
)

_FORBIDDEN = (
    "punt_lux.hub",
    "punt_lux.commands",
    "punt_lux.operations.facade",
    "punt_lux.display",
    "punt_lux.pty",
)


@pytest.mark.parametrize("module", ["punt_lux", "punt_lux.client", "punt_lux.service"])
def test_public_import_is_runtime_isolated(module: str) -> None:
    assert_isolated(module, _FORBIDDEN)


@pytest.mark.parametrize(
    "module",
    [
        "punt_lux.operations.models",
        "punt_lux.client.identity_headers",
        "punt_lux.client.header_value",
        "punt_lux.commands._ports",
        "punt_lux.commands._frame_ports",
        "punt_lux.commands._topic_ports",
        "punt_lux.service._service_spec",
        "punt_lux.hub.session_callback",
        "punt_lux.hub.menu_models",
        "punt_lux.hub.menu_action",
        "punt_lux.hub.connection_scoped_id",
        "punt_lux.hub.frame_ownership",
    ],
)
def test_old_contract_paths_have_no_aliases(module: str) -> None:
    assert_not_importable(module)


@pytest.mark.parametrize(
    "module",
    package_modules("punt_lux.wire.ops") + package_modules("punt_lux.wire.operations"),
)
def test_new_contract_modules_import_in_fresh_process(module: str) -> None:
    assert_importable(module)


def test_root_does_not_reexport_a_hub_command() -> None:
    import punt_lux

    assert not hasattr(punt_lux, "__all__")
    assert not hasattr(punt_lux, "ping")
