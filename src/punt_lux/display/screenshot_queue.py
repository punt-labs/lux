"""ScreenshotQueue -- one capture per frame, read before the swap, sent after it.

The drawn frame is in the back buffer only until the swap, so the pixels are
read in ``before_swap``. The PNG is written and the reply sent in
``after_swap``, after the acks the swap releases, so the Hub's ordered reply
stream is unchanged. A read that fails is answered at once, before the swap:
there is no frame to carry across it. One request waits at a time; a request
that arrives while another waits is answered at once with an error, never
allowed to replace it: the requester of a replaced request would wait out its
whole timeout for a reply that never comes.
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.framebuffer_capture import FramebufferCapture
from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.wire.model import QueryResponse

if TYPE_CHECKING:
    import socket
    from pathlib import Path

    from PIL import Image

    from punt_lux.display.client_sender import ClientSender
    from punt_lux.display.display_log import ErrorRecorder

logger = logging.getLogger(__name__)

__all__ = ["ScreenshotQueue"]

_METHOD = "screenshot"


@final
class ScreenshotQueue:
    """Holds the requester of the next frame's screenshot, and the frame once read."""

    _sender: ClientSender
    _record_error: ErrorRecorder
    _directory: Path
    _waiting: socket.socket | None  # None = no screenshot waits for the next frame
    # PY-TS-14 OK: None between frames; set by before_swap, cleared by after_swap.
    _read: tuple[socket.socket, Image.Image] | None
    __slots__ = ("_directory", "_read", "_record_error", "_sender", "_waiting")

    def __new__(
        cls, record_error: ErrorRecorder, sender: ClientSender, directory: Path
    ) -> Self:
        self = super().__new__(cls)
        self._sender = sender
        self._record_error = record_error
        self._directory = directory
        self._waiting = None
        self._read = None
        return self

    def request(self, sock: socket.socket) -> None:
        """Take a screenshot for ``sock`` at the next frame, or refuse it at once."""
        if self._waiting is not None:
            busy = QueryResponse(
                method=_METHOD,
                error="a screenshot is already waiting for the next frame",
            )
            self._sender.reply_to_client(sock, busy)
            return
        self._waiting = sock

    def before_swap(self) -> None:
        """Read the frame just drawn for the waiting requester, while GL_BACK holds it.

        A read that fails is answered now with its error: nothing waits for the swap.
        """
        sock = self._waiting
        if sock is None:
            return
        self._waiting = None
        try:
            frame = FramebufferCapture.read_frame()
        except ProgrammerError:
            raise
        except Exception as exc:  # the reply carries the failure
            logger.exception("Screenshot read failed")
            self._sender.reply_to_client(sock, self._failed_screenshot(exc))
            return
        self._read = (sock, frame)

    def after_swap(self) -> None:
        """Write the frame read before this swap and reply to its requester."""
        read = self._read
        if read is None:
            return
        self._read = None
        sock, frame = read
        try:
            path = self._save(self._directory, frame)
        except ProgrammerError:
            raise
        except Exception as exc:  # the reply carries the failure
            logger.exception("Screenshot write failed")
            self._sender.reply_to_client(sock, self._failed_screenshot(exc))
            return
        reply = QueryResponse(method=_METHOD, result={"path": path})
        self._sender.reply_to_client(sock, reply)

    def _failed_screenshot(self, exc: Exception) -> QueryResponse:
        """Record the failure in the display's log; the reply that carries it."""
        self._record_error("error", str(exc), _METHOD)
        return QueryResponse(method=_METHOD, error=str(exc))

    @staticmethod
    def _save(directory: Path, image: Image.Image) -> str:
        """Write the PNG owner-only into ``directory``, the display's own.

        The directory is created by this process at mode 0700 and refused if
        another user owns it: a shared temporary root would let that user
        pre-create it and redirect the write. The file is opened once, by
        descriptor, so no path is reopened after the exclusive create.
        """
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.stat()
        if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode):
            msg = f"screenshot directory {directory} is not owned by this user"
            raise PermissionError(msg)
        fd, path = tempfile.mkstemp(
            suffix=".png", prefix="lux-screenshot-", dir=directory
        )
        with os.fdopen(fd, "wb") as f:
            image.save(f, format="PNG")
        return path
