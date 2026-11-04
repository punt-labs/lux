"""set_process_title really renames the process; a missing setproctitle is fatal."""

from __future__ import annotations

import subprocess
import sys

from setproctitle import getproctitle, setproctitle

from punt_lux.proctitle import set_process_title


def test_set_process_title_changes_the_process_title():
    original = getproctitle()
    try:
        set_process_title("lux-proctitle-test")
        assert getproctitle() == "lux-proctitle-test"
    finally:
        setproctitle(original)


def test_import_fails_when_setproctitle_is_missing():
    # setproctitle is a required base dependency, so its absence is a broken
    # install. Blocking the import in a fresh interpreter must make
    # `import punt_lux.proctitle` raise, not leave a silent no-op behind.
    code = "import sys; sys.modules['setproctitle'] = None; import punt_lux.proctitle"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
    assert "setproctitle" in result.stderr
