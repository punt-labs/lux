"""Per-viewer flow: bounded live backlog, credit and ordered snapshot resets."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self

from punt_lux.pty.credit import CreditWindow
from punt_lux.pty.viewer_outbox import ViewerOutbox
from punt_lux.pty.viewer_size import ViewerSize

if TYPE_CHECKING:
    from punt_lux.terminal.output import SessionSnapshot
    from punt_lux.wire.stream.frames import Frame


class ViewerFlow:
    _channel: int
    _credit: CreditWindow
    _outbox: ViewerOutbox
    _repaint: bool
    _screen_only: bool
    _size: ViewerSize

    def __new__(cls, channel: int) -> Self:
        self = super().__new__(cls)
        self._channel = channel
        self._credit = CreditWindow()
        self._outbox = ViewerOutbox(channel)
        self._repaint = False
        self._screen_only = False
        self._size = ViewerSize()
        return self

    @property
    def size(self) -> ViewerSize:
        return self._size

    @property
    def close_sent(self) -> bool:
        return self._outbox.close_sent

    @property
    def lag_bytes(self) -> int:
        return self._outbox.lag_bytes

    @property
    def inflight(self) -> int:
        return self._credit.inflight

    @property
    def wants_repaint(self) -> bool:
        return (
            self._repaint and self._outbox.snapshot_sent and self._credit.available > 0
        )

    def request_repaint(self) -> None:
        """Drop the unsent backlog and ask the publisher for a fresh snapshot."""
        self._outbox.drop_tail()
        self._repaint = True

    def prepare(
        self,
        checkpoint: SessionSnapshot,
        description: dict[str, object],
        *,
        initial: bool = False,
    ) -> None:
        """Drop only unsent backlog; old in-flight bytes retain their credit debt."""
        self._size.measured((checkpoint.cols, checkpoint.rows))
        metadata = checkpoint.to_dict()
        metadata.update(
            channel=self._channel,
            ended=description["ended"],
            exit_code=description["exit_code"],
        )
        self._outbox.begin(
            checkpoint.data, b"" if initial else json.dumps(metadata).encode()
        )
        # A screen-only repaint is not a checkpoint: raw output stays
        # suppressed until a binary checkpoint at ground can be cut. The next
        # cut waits for a reason (see ``append``): an identical repaint would
        # replace the Display's buffer and wipe its selection. An ended
        # session produces no more output, so its last repaint is final.
        self._screen_only = not (checkpoint.is_checkpoint or description["ended"])
        self._repaint = False
        if description["ended"]:
            self.finish("exited", description["exit_code"])

    def append(self, data: bytes) -> None:
        if self._screen_only:
            # The program moved while the viewer has only a screen repaint:
            # the screen is stale, so schedule one cut (not one per pump).
            self._repaint = self._repaint or bool(data)
        elif self._repaint or self._outbox.close_sent:
            return
        elif self._outbox.overflows(len(data)):
            self.request_repaint()
        elif data:
            self._outbox.push(data)

    def acknowledge(self, amount: int) -> None:
        self._credit.acknowledge(amount)

    def finish(self, reason: str, exit_code: object = None) -> None:
        if reason != "exited":
            self._outbox.abandon()
            self._repaint = self._screen_only = False
        self._outbox.finish(reason, exit_code)

    def drain(self) -> list[Frame]:
        return self._outbox.drain(self._credit, resyncing=self._repaint)
