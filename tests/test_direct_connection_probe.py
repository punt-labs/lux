"""Tests for ``scripts/direct_connection_probe.py`` -- exit codes and messages.

The probe must exit non-zero on a failed tool call (not print "OK") and turn an
unreachable luxd into a one-line hint rather than a raw ExceptionGroup traceback.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from mcp.types import TextContent

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    """Load ``scripts/direct_connection_probe.py`` as a module."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "direct_connection_probe.py"
    spec = importlib.util.spec_from_file_location(
        "direct_connection_probe", script_path
    )
    if spec is None or spec.loader is None:
        msg = f"Could not load spec for {script_path}"
        raise RuntimeError(msg)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["direct_connection_probe"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop("direct_connection_probe", None)
        raise
    return mod


class _RefusingClient:
    """A transport stand-in whose connection attempt is refused."""

    async def __aenter__(self) -> tuple[None, None, None]:
        raise ConnectionError("connection refused")

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSession:
    """A ClientSession stand-in whose ``call_tool`` returns a canned result."""

    _result: object
    __slots__ = ("_result",)

    def __new__(cls, result: object) -> _FakeSession:
        self = super().__new__(cls)
        self._result = result
        return self

    async def initialize(self) -> SimpleNamespace:
        return SimpleNamespace(serverInfo=SimpleNamespace(name="luxd", version="0"))

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(tools=[])

    async def call_tool(self, name: str, args: dict[str, object]) -> object:
        return self._result


def _patch_client(
    monkeypatch: pytest.MonkeyPatch, probe: ModuleType, session: object
) -> None:
    """Point the probe's transport and client factories at in-memory fakes."""

    @asynccontextmanager
    async def _streams(url: str) -> AsyncGenerator[tuple[None, None, None]]:
        yield (None, None, None)

    @asynccontextmanager
    async def _client(read: object, write: object) -> AsyncGenerator[object]:
        yield session

    monkeypatch.setattr(probe, "streamable_http_client", _streams)
    monkeypatch.setattr(probe, "ClientSession", _client)


def test_failed_tool_call_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: ModuleType,
) -> None:
    """An ``isError=True`` list_scenes exits 1 with the payload on stderr."""
    result = SimpleNamespace(
        isError=True, content=[TextContent(type="text", text="scene boom")]
    )
    _patch_client(monkeypatch, probe, _FakeSession(result))

    rc = asyncio.run(probe._probe("http://127.0.0.1:9/mcp"))

    captured = capsys.readouterr()
    assert rc == 1
    assert "list_scenes failed: scene boom" in captured.err
    assert "direct connection OK" not in captured.out


def test_ok_tool_call_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: ModuleType,
) -> None:
    """An ``isError=False`` list_scenes prints the transcript and exits 0."""
    result = SimpleNamespace(
        isError=False, content=[TextContent(type="text", text="[]")]
    )
    _patch_client(monkeypatch, probe, _FakeSession(result))

    rc = asyncio.run(probe._probe("http://127.0.0.1:9/mcp"))

    assert rc == 0
    assert "direct connection OK" in capsys.readouterr().out


def test_reports_missing_port_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: ModuleType,
) -> None:
    """No port file exits 1 with a start-luxd hint, not a traceback."""

    def _no_port(self: object) -> None:
        return None

    monkeypatch.setattr("punt_lux.hub_paths.HubPaths.read_port", _no_port)

    rc = probe.main()

    assert rc == 1
    assert "luxd is not running" in capsys.readouterr().err


def test_reports_unreachable_luxd(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: ModuleType,
) -> None:
    """A stale port file / dead luxd exits 1 with a hint, not an ExceptionGroup."""

    def _port(self: object) -> int:
        return 8430

    def _refuse(url: str) -> _RefusingClient:
        return _RefusingClient()

    monkeypatch.setattr("punt_lux.hub_paths.HubPaths.read_port", _port)
    monkeypatch.setattr(probe, "streamable_http_client", _refuse)

    rc = probe.main()

    assert rc == 1
    assert "luxd not reachable at http://127.0.0.1:8430/mcp" in capsys.readouterr().err


@pytest.mark.e2e
def test_no_port_file_exits_one_as_subprocess(tmp_path: Path) -> None:
    """Run the probe as a real process against real HubPaths glue.

    An empty ``HOME`` gives HubPaths a state dir with no port file, so the real
    ``main()`` takes the no-port-file branch and exits 1 — proving the glue, not
    just the branch a monkeypatched ``read_port`` exercises.
    """
    script = Path(__file__).resolve().parent.parent / "scripts"
    script = script / "direct_connection_probe.py"
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert "luxd is not running" in result.stderr
