"""Test programs: a test daemon starts the command listed under a session's label."""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from punt_lux.pty.holder import PtyHolder
from punt_lux.pty.process_factory import ProcessFactory
from punt_lux.pty.process_port import ProcessPort
from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.stream.control import WIRE_VERSION
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.replies import SuccessReply
from tests.pty.wire_client import WireClient

ENVIRONMENT_KEY = "LUX_TEST_LAUNCHERS_FILE"


class LauncherTable:
    """A JSON file of session label to command line, shared with a daemon."""

    _path: Path

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        return self

    def commands(self) -> Mapping[str, str]:
        """The current table; empty before the first registration."""
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())  # type: ignore[no-any-return]  # JSON object

    def register(self, command: str) -> str:
        """List ``command`` under a fresh label and return the label."""
        table = dict(self.commands())
        name = f"test-{len(table) + 1}"
        table[name] = command
        self._path.write_text(json.dumps(table))
        return name


class TestLaunchers:
    """Process creator for a test daemon: a listed label runs its command."""

    __test__ = False  # not a pytest collection target

    _table: LauncherTable

    def __new__(cls, table: LauncherTable) -> Self:
        self = super().__new__(cls)
        self._table = table
        return self

    @classmethod
    def from_environment(cls) -> Self:
        """Read the table file a test passed to its daemon subprocess."""
        return cls(LauncherTable(Path(os.environ[ENVIRONMENT_KEY])))

    def __call__(self, request: NewRequest) -> ProcessPort:
        command = self._table.commands().get(request.label)
        if command is None:
            return ProcessFactory.start(request)
        return PtyHolder(shlex.split(command), cols=request.cols, rows=request.rows)


class Launch:
    """Starts a listed program as a session on a running test daemon."""

    _socket: Path
    _table: LauncherTable

    def __new__(cls, socket_path: Path, table: LauncherTable) -> Self:
        self = super().__new__(cls)
        self._socket, self._table = socket_path, table
        return self

    def session(self, command: str, *, cols: int = 80, rows: int = 24) -> str:
        """Run ``command`` as a new session on the daemon and return its id."""
        label = self._table.register(command)
        client = WireClient(self._socket)
        try:
            hello = HelloRequest(1, WIRE_VERSION, snapshot_version())
            assert isinstance(client.request(hello), SuccessReply)
            reply = client.request(NewRequest(2, label, "", cols, rows))
            assert isinstance(reply, SuccessReply), reply
            return str(reply.result["session"])
        finally:
            client.close()


class CommandFactory:
    """Process creator that runs one fixed command line, whatever is requested."""

    _command: str

    def __new__(cls, command: str) -> Self:
        self = super().__new__(cls)
        self._command = command
        return self

    def __call__(self, request: NewRequest) -> ProcessPort:
        return PtyHolder(
            shlex.split(self._command), cols=request.cols, rows=request.rows
        )
