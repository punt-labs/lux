"""ScreenshotQueue -- one capture per frame, read before the swap, sent after it."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

from PIL import Image

from punt_lux.display.screenshot_queue import ScreenshotQueue
from punt_lux.wire.model import QueryResponse

if TYPE_CHECKING:
    import socket
    from pathlib import Path

    from punt_lux.display.display_log import ErrorSeverity

_A = cast("socket.socket", object())
_B = cast("socket.socket", object())
_READ = "punt_lux.display.screenshot_queue.FramebufferCapture.read_frame"

type _Recorded = tuple[ErrorSeverity, str, str]


def _frame() -> Image.Image:
    return Image.new("RGBA", (4, 2), (255, 0, 0, 255))


def _queue(tmp_path: Path) -> tuple[ScreenshotQueue, MagicMock, list[_Recorded]]:
    sender = MagicMock()
    recorded: list[_Recorded] = []

    def record(severity: ErrorSeverity, message: str, context: str) -> None:
        recorded.append((severity, message, context))

    return ScreenshotQueue(record, sender, tmp_path / "shots"), sender, recorded


def _replies(sender: MagicMock) -> list[tuple[object, QueryResponse]]:
    return [tuple(c.args) for c in sender.reply_to_client.call_args_list]


def test_nothing_is_read_or_sent_while_nobody_waits(tmp_path: Path) -> None:
    queue, sender, _ = _queue(tmp_path)
    with patch(_READ) as read:
        queue.before_swap()
        queue.after_swap()

    read.assert_not_called()
    sender.reply_to_client.assert_not_called()


def test_the_frame_is_read_before_the_swap_and_replied_after_it(
    tmp_path: Path,
) -> None:
    queue, sender, _ = _queue(tmp_path)
    queue.request(_A)

    with patch(_READ, return_value=_frame()) as read:
        queue.before_swap()
        read.assert_called_once()
        sender.reply_to_client.assert_not_called()

        queue.after_swap()

    ((sock, reply),) = _replies(sender)
    assert sock is _A
    assert reply.error is None
    with Image.open(reply.result["path"]) as shot:
        assert shot.size == (4, 2)


def test_the_png_lands_in_the_displays_own_directory_owner_only(
    tmp_path: Path,
) -> None:
    # Never a shared temporary root: another local user could pre-create the
    # directory and redirect the write. The directory is made by this process,
    # owner-only, under the display's runtime directory.
    queue, sender, _ = _queue(tmp_path)
    queue.request(_A)
    with patch(_READ, return_value=_frame()):
        queue.before_swap()
        queue.after_swap()

    ((_, reply),) = _replies(sender)
    path = tmp_path / "shots" / reply.result["path"].rsplit("/", 1)[1]
    assert path.is_file()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_directory_this_process_does_not_own_is_refused(tmp_path: Path) -> None:
    (tmp_path / "shots").mkdir(mode=0o777)
    queue, sender, recorded = _queue(tmp_path)
    queue.request(_A)
    with (
        patch(_READ, return_value=_frame()),
        patch("punt_lux.display.screenshot_queue.os.getuid", lambda: -1),
    ):
        queue.before_swap()
        queue.after_swap()

    ((sock, reply),) = _replies(sender)
    assert sock is _A
    assert reply.error is not None
    assert "not owned" in reply.error
    assert recorded == [("error", reply.error, "screenshot")]
    assert list((tmp_path / "shots").iterdir()) == []


def test_a_read_that_fails_is_answered_before_the_swap(tmp_path: Path) -> None:
    # Nothing to carry across the swap: the error reply goes out at once, and
    # after_swap has nothing to send.
    queue, sender, recorded = _queue(tmp_path)
    queue.request(_A)

    with patch(_READ, side_effect=RuntimeError("no GL context")):
        queue.before_swap()
    ((sock, reply),) = _replies(sender)
    assert sock is _A
    assert reply.error == "no GL context"
    assert recorded == [("error", "no GL context", "screenshot")]

    queue.after_swap()
    assert sender.reply_to_client.call_count == 1


def test_a_request_arriving_after_the_read_waits_for_the_next_frame(
    tmp_path: Path,
) -> None:
    # The read for this frame has happened; B must not receive A's pixels, and
    # must not be refused either, since nothing of B's is in flight.
    queue, sender, _ = _queue(tmp_path)
    queue.request(_A)
    with patch(_READ, return_value=_frame()) as read:
        queue.before_swap()

        queue.request(_B)
        queue.after_swap()
        assert [s for s, _ in _replies(sender)] == [_A]

        queue.before_swap()
        queue.after_swap()
        assert read.call_count == 2
    assert [s for s, _ in _replies(sender)] == [_A, _B]


def test_a_second_request_while_one_waits_is_refused_at_once(tmp_path: Path) -> None:
    queue, sender, _ = _queue(tmp_path)
    queue.request(_A)

    queue.request(_B)

    ((sock, busy),) = _replies(sender)
    assert sock is _B
    assert busy.error is not None
