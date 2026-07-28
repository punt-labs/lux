"""Unit tests for punt_lux.domain.hub.display_workers — the worker facade."""

from __future__ import annotations

from typing import cast

from punt_lux.domain.hub.display_workers import DisplayWorkers
from punt_lux.domain.hub.liveness import DisplayLiveness
from punt_lux.domain.hub.replicator import HubReplicator


class _Recorder:
    """Records start/stop calls against a shared order log, tagged by name."""

    _name: str
    _log: list[str]

    def __new__(cls, name: str, log: list[str]) -> _Recorder:
        self = super().__new__(cls)
        self._name = name
        self._log = log
        return self

    def start(self) -> None:
        self._log.append(f"{self._name}.start")

    def stop(self) -> None:
        self._log.append(f"{self._name}.stop")


class TestDisplayWorkers:
    """The facade starts the replicator before the keepalive and stops in reverse."""

    def test_start_then_stop_ordering(self) -> None:
        log: list[str] = []
        replicator = _Recorder("replicator", log)
        liveness = _Recorder("liveness", log)
        workers = DisplayWorkers(
            cast("HubReplicator", replicator), cast("DisplayLiveness", liveness)
        )

        workers.start()
        workers.stop()

        # Replicator starts first (the writer must exist before the guard); the
        # keepalive stops first so it cannot reconnect a connection being torn down.
        assert log == [
            "replicator.start",
            "liveness.start",
            "liveness.stop",
            "replicator.stop",
        ]

    def test_replicator_property_returns_the_writer(self) -> None:
        log: list[str] = []
        replicator = _Recorder("replicator", log)
        workers = DisplayWorkers(
            cast("HubReplicator", replicator),
            cast("DisplayLiveness", _Recorder("liveness", log)),
        )
        assert workers.replicator is cast("HubReplicator", replicator)
