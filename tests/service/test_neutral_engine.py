"""A non-Lux daemon supplies identities, diagnostics and optional disk policy."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from punt_service import ServiceActionFailedError, ServiceManager, ServiceSpec
from punt_service._binary_sweep import BinarySweepReport
from punt_service._empty_binary_sweep import EmptyBinarySweep


class ExampleService(ServiceManager):
    _SPEC: ClassVar[ServiceSpec] = ServiceSpec(
        display_name="exampled",
        launchd_label="org.example.daemon",
        systemd_unit="exampled",
        systemd_description="Example daemon",
        binary_name="exampled",
        extra_args=(),
        cli_verb="daemon",
        process_name="exampled",
        cli_name="example",
    )


def test_no_disk_policy_is_empty_and_never_mutates() -> None:
    empty = EmptyBinarySweep()
    assert empty.is_clean()
    assert empty.diagnose() == BinarySweepReport(outcomes=())
    assert empty.sweep() == BinarySweepReport(outcomes=())


def test_product_diagnostics_are_optional() -> None:
    assert ExampleService._SPEC.failure_message("stop") == "exampled stop failed."


def test_backend_failure_has_no_lux_logging_policy() -> None:
    with patch("punt_service.platform_classes") as classes:
        backend = classes.return_value.backend.return_value
        backend.config_path.return_value = Path(__file__)
        backend.start.return_value = False
        manager = ExampleService()
        with pytest.raises(
            ServiceActionFailedError, match=r"^exampled start failed\.$"
        ):
            manager.start()


def test_product_disk_policy_failure_prevents_installation() -> None:
    policy = MagicMock()
    policy.sweep.side_effect = RuntimeError("product migration refused")
    with patch("punt_service.platform_classes") as classes:
        manager = ExampleService(binary_sweep=policy)
        with pytest.raises(RuntimeError, match="product migration refused"):
            manager.install()
        classes.return_value.backend.return_value.install.assert_not_called()
