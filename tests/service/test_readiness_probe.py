"""Bounded socket ownership is sufficient without a separate handshake/retry."""

from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.service._readiness_probe import ReadinessProbe
from punt_lux.service.display_paths import DisplayPaths


def test_one_local_connection_checks_liveness_and_ownership() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-") as directory:
        paths = DisplayPaths(Path(directory) / "d.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(paths.socket_path))
            listener.listen(5)
            assert ReadinessProbe(paths).local(os.getpid(), 0.1)
            assert not ReadinessProbe(paths).local(os.getpid() + 1, 0.1)


def test_an_absent_socket_is_not_a_match(tmp_path: Path) -> None:
    assert not ReadinessProbe(DisplayPaths(tmp_path / "absent")).local(502, 0.1)


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionRefusedError()])
def test_timeout_is_one_attempt_with_no_handshake_or_retry(error: OSError) -> None:
    with patch("punt_lux.service._readiness_probe.socket.socket") as make_socket:
        probe = make_socket.return_value.__enter__.return_value
        probe.connect.side_effect = error
        assert not ReadinessProbe(MagicMock()).local(502, 0.125)
    probe.settimeout.assert_called_once_with(0.125)
    probe.connect.assert_called_once()
    probe.recv.assert_not_called()
