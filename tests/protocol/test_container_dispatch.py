"""Unit tests for the container-recursion dispatch registry."""

from __future__ import annotations

from typing import Any

import pytest

from punt_lux.protocol.elements.container_dispatch import ContainerDispatch


class TestContainerDispatch:
    def test_to_dict_raises_before_install(self) -> None:
        dispatch = ContainerDispatch()
        with pytest.raises(RuntimeError, match="encode dispatcher installed"):
            _ = dispatch.to_dict

    def test_from_dict_raises_before_install(self) -> None:
        dispatch = ContainerDispatch()
        with pytest.raises(RuntimeError, match="decode dispatcher installed"):
            _ = dispatch.from_dict

    def test_install_to_dict_binds_the_function(self) -> None:
        dispatch = ContainerDispatch()

        def encode(_elem: Any) -> dict[str, Any]:
            return {"kind": "x"}

        dispatch.install_to_dict(encode)
        assert dispatch.to_dict is encode

    def test_install_from_dict_binds_the_function(self) -> None:
        dispatch = ContainerDispatch()

        def decode(raw: dict[str, Any]) -> Any:
            return raw

        dispatch.install_from_dict(decode)
        assert dispatch.from_dict is decode

    def test_instances_are_independent(self) -> None:
        # Each registry holds its own targets — installing on one does not
        # leak into another (guards against shared module-global state).
        first = ContainerDispatch()
        second = ContainerDispatch()
        first.install_from_dict(lambda raw: raw)
        with pytest.raises(RuntimeError, match="decode dispatcher installed"):
            _ = second.from_dict
