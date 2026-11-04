"""Smoke test: package imports, version is set, the public client is exported."""

from __future__ import annotations

import subprocess
import sys

import pytest

# The library surface a consumer imports to drive luxd — the public facade and
# the request/result types it speaks, plus the one exceptional error. The
# transport-flavoured names (the private REST transport, LuxHubClient) are not
# in the public __all__: consumers hold LuxClient and reach its noun-grouped
# accessors.
_PUBLIC_CLIENT_API = (
    "LuxClient",
    "ClientIdentity",
    "RenderRequest",
    "RenderTableRequest",
    "SceneShown",
    "Pong",
    "OpError",
    "HubUnavailableError",
)


def test_version_matches_metadata():
    from importlib.metadata import version

    from punt_lux import __version__

    assert __version__
    assert __version__ == version("punt-lux")


def test_missing_distribution_fails_import_rather_than_reporting_a_version(
    monkeypatch: pytest.MonkeyPatch,
):
    # An uninstalled package is a broken environment: importing it must raise
    # PackageNotFoundError, never yield a made-up "0.0.0".
    import importlib
    from importlib.metadata import PackageNotFoundError, version

    import punt_lux

    real_version = version("punt-lux")

    def _not_installed(distribution_name: str) -> str:
        raise PackageNotFoundError(distribution_name)

    with monkeypatch.context() as patched:
        patched.setattr("importlib.metadata.version", _not_installed)
        with pytest.raises(PackageNotFoundError):
            importlib.reload(punt_lux)

    # The failed reload ran with the patch in place; reload again unpatched so
    # the module every other test shares is back in its normal state.
    importlib.reload(punt_lux)
    assert punt_lux.__version__ == real_version


def test_package_imports():
    import punt_lux

    assert punt_lux.__all__ is not None


def test_public_client_and_its_types_are_exported():
    # LuxClient is the public library facade — consumers (vox and others) hold it
    # and reach the Hub through its noun-grouped accessors. It and the types
    # needed to call it fully typed are in __all__ and importable from the
    # top-level package.
    import punt_lux

    for name in _PUBLIC_CLIENT_API:
        assert name in punt_lux.__all__, name
        assert hasattr(punt_lux, name), name


def test_public_import_pulls_no_display_extras():
    # The library surface must import without the [display] extra, so a bare
    # `import punt_lux` must not drag imgui/numpy/Pillow/OpenGL. Checked in a fresh
    # interpreter because other tests in this process may already hold them.
    code = (
        "import punt_lux, sys; "
        "print([m for m in ('imgui_bundle', 'numpy', 'PIL', 'OpenGL') "
        "if m in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", result.stdout


def test_public_client_imports_without_display_extras_in_a_fresh_interpreter():
    # A consumer's real call: `from punt_lux import LuxClient, ...` must succeed
    # in an interpreter that never loaded the display stack.
    names = ", ".join(_PUBLIC_CLIENT_API)
    result = subprocess.run(
        [sys.executable, "-c", f"from punt_lux import {names}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0, result.stderr
