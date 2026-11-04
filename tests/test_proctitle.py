"""set_process_title really renames the process; a missing setproctitle is fatal."""

from __future__ import annotations

import subprocess
import sys

import pytest
from setproctitle import getproctitle, setproctitle

from punt_lux.proctitle import set_process_title


def test_set_process_title_changes_the_process_title():
    original = getproctitle()
    try:
        set_process_title("lux-proctitle-test")
        assert getproctitle() == "lux-proctitle-test"
    finally:
        setproctitle(original)


@pytest.mark.parametrize(
    "module",
    ["punt_lux.proctitle", "punt_lux.luxd", "punt_lux.luxd_display"],
)
def test_import_fails_when_setproctitle_is_missing(module: str):
    # setproctitle is a required base dependency, so its absence is a broken
    # install. Blocking the import in a fresh interpreter must make every module
    # that names the process raise at import, not leave a silent no-op behind
    # (`lux hub restart` and `lux display restart` poll pgrep for those names).
    code = f"import sys; sys.modules['setproctitle'] = None; import {module}"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    last_line = result.stderr.strip().splitlines()[-1]
    assert last_line.startswith("ModuleNotFoundError: import of setproctitle halted"), (
        result.stderr
    )
