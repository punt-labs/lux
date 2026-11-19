"""Each spawned Python entry detaches before constructing its application."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux.ptyd.__main__ import PtyEntryPoint
from punt_lux.ptyd.menu_entry import MenuEntryPoint


class ReachedStartupError(Exception):
    pass


@pytest.mark.parametrize(
    ("entry", "startup"),
    [
        (PtyEntryPoint, "punt_lux.ptyd.__main__.argparse.ArgumentParser"),
        (MenuEntryPoint, "punt_lux.ptyd.menu_entry.MenuEntryPoint.serve"),
    ],
)
@pytest.mark.parametrize("already_detached", [False, True])
def test_entry_detaches_before_startup(
    entry: type[PtyEntryPoint] | type[MenuEntryPoint],
    startup: str,
    already_detached: bool,
) -> None:
    with (
        patch("os.getpid", return_value=100),
        patch("os.getsid", return_value=100 if already_detached else 99),
        patch("os.setsid") as detach,
        patch("sys.argv", ["entry", "42"]),
        patch(startup, side_effect=ReachedStartupError),
        pytest.raises(ReachedStartupError),
    ):
        entry.main()
    assert detach.call_count == (0 if already_detached else 1)


@pytest.mark.parametrize("entry", [PtyEntryPoint, MenuEntryPoint])
def test_entry_does_not_ignore_a_detachment_failure(
    entry: type[PtyEntryPoint] | type[MenuEntryPoint],
) -> None:
    with (
        patch("os.getpid", return_value=100),
        patch("os.getsid", return_value=99),
        patch("os.setsid", side_effect=PermissionError("denied")),
        pytest.raises(PermissionError, match="denied"),
    ):
        entry.main()
