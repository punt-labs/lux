"""Namespace ownership, direct public imports and distribution metadata."""

from __future__ import annotations

import importlib
import subprocess
import sys
from importlib import metadata

import pytest
from typer.testing import CliRunner

from punt_lux.cli.__main__ import app


def test_namespace_has_no_root_exports() -> None:
    import punt_lux

    assert vars(punt_lux).get("__file__") is None
    assert punt_lux.__spec__ is not None
    assert punt_lux.__spec__.submodule_search_locations is not None
    for name in ("__all__", "__version__", "LuxClient", "RenderRequest"):
        assert not hasattr(punt_lux, name)


@pytest.mark.parametrize("args", [["--version"], ["version"]])
def test_version_matches_metadata(args: list[str]) -> None:
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0
    assert result.stdout.strip() == f"lux {metadata.version('punt-lux')}"


def test_missing_metadata_fails_version_not_namespace_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import punt_lux

    def unavailable(distribution: str) -> str:
        raise metadata.PackageNotFoundError(distribution)

    monkeypatch.setattr(metadata, "version", unavailable)
    importlib.reload(punt_lux)
    assert vars(punt_lux).get("__file__") is None
    result = CliRunner().invoke(app, ["--version"])
    assert isinstance(result.exception, metadata.PackageNotFoundError)


def test_public_client_imports_without_display_extras_in_a_fresh_interpreter() -> None:
    code = """
import sys
from punt_lux.client import LuxClient
from punt_lux.client.rest_transport import HubUnavailableError
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.operations import RenderRequest, RenderTableRequest, SceneShown
from punt_lux.wire.operations import Pong, OpError
assert all((LuxClient, HubUnavailableError, ClientIdentity, RenderRequest,
            RenderTableRequest, SceneShown, Pong, OpError))
forbidden = {'imgui_bundle', 'numpy', 'PIL', 'OpenGL', 'fastapi', 'starlette', 'mcp'}
assert not forbidden & sys.modules.keys()
"""
    subprocess.run([sys.executable, "-P", "-c", code], check=True, capture_output=True)


def test_cli_module_is_executable_but_namespace_root_is_not() -> None:
    cli = subprocess.run(
        [sys.executable, "-P", "-m", "punt_lux.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr
    root = subprocess.run(
        [sys.executable, "-P", "-m", "punt_lux"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert root.returncode != 0
    assert "punt_lux.__main__" in root.stderr
