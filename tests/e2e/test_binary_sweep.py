"""Fidelity-control e2e: DiskBinaryLegacySweep against a REAL ``uv tool dir``.

No mock can prove that this design's parsing of uv's actual stdout format is
correct -- the one thing a mocked subprocess call cannot exercise. This test
runs the real ``uv`` subprocess (no mocking of that boundary) against a
scratch symlink shaped like ``~/.local/bin/luxd``, but pointed at a
disposable file planted inside the REAL punt-lux uv tool directory this
machine reports -- proving the sweep correctly recognizes and removes its
own shim end to end. Never touches the operator's real
``~/.local/bin/luxd`` (docs/architecture/binary-rename-migration.md §8.2).

Run via ``make test-e2e`` -- excluded from the default ``make test`` gate.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux._binary_sweep_disk import DiskBinaryLegacySweep
from punt_lux.service import HUB_SPEC

pytestmark = pytest.mark.e2e

_SCRATCH_NAME = "luxd-e2e-scratch-shim"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_sweep_removes_an_owned_shim_under_the_real_uv_tool_dir(
    tmp_path: Path,
) -> None:
    real_tool_dir = subprocess.run(
        ["uv", "tool", "dir"], capture_output=True, text=True, check=True
    ).stdout.strip()

    fake_home = tmp_path / "home"
    bin_dir = fake_home / ".local" / "bin"
    bin_dir.mkdir(parents=True)

    # Plant the disposable target inside the REAL punt-lux tool dir this
    # machine reports -- the exact path DiskBinaryLegacySweep's own
    # _resolve_tool_root() will compute from the real uv subprocess call.
    # The scratch name never collides with a real installed entrypoint.
    real_punt_lux_bin = Path(real_tool_dir) / "punt-lux" / "bin"
    real_punt_lux_bin.mkdir(parents=True, exist_ok=True)
    shim = real_punt_lux_bin / _SCRATCH_NAME
    shim.write_text("#!/fake/venv/bin/python3\nfrom punt_lux.luxd import main\n")
    shim.chmod(0o755)
    link = bin_dir / _SCRATCH_NAME
    link.symlink_to(shim)

    try:
        spec = replace(HUB_SPEC, legacy_binary_names=(_SCRATCH_NAME,))
        with patch("punt_lux._binary_sweep_disk.Path.home", return_value=fake_home):
            report = DiskBinaryLegacySweep(spec).sweep()

        assert report.all_clean
        assert report.outcomes[0].ownership_verified is True
        assert not link.exists()
        assert not link.is_symlink()
    finally:
        link.unlink(missing_ok=True)
        shim.unlink(missing_ok=True)
