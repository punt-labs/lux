"""Static endpoint selection and worker composition, independent of wire formats."""

from __future__ import annotations

from typing import Self, cast, final

from punt_lux.hub.peripheral_key import PeripheralKey
from punt_lux.hub.peripheral_ports import PeripheralStatus, PeripheralWorkers

__all__ = ["PeripheralRegistry"]


@final
class PeripheralRegistry:
    """Own one endpoint per kind and freeze wiring when lifecycle begins."""

    _endpoints: dict[object, PeripheralStatus]
    _kinds: set[str]
    _workers: dict[object, PeripheralWorkers]
    _sealed: bool
    __slots__ = ("_endpoints", "_kinds", "_sealed", "_workers")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._endpoints = {}
        self._kinds = set()
        self._workers = {}
        self._sealed = False
        return self

    def register[P: PeripheralStatus](self, key: PeripheralKey[P], endpoint: P) -> None:
        """Register a typed endpoint, rejecting a second endpoint of its kind."""
        self._require_mutable()
        if key.kind in self._kinds:
            raise ValueError(f"peripheral kind already registered: {key.kind}")
        self._endpoints.update((key.bind(endpoint),))
        self._kinds.add(key.kind)

    def require[P: PeripheralStatus](self, key: PeripheralKey[P]) -> P:
        """Resolve the exact typed key without connecting or synthesizing status."""
        try:
            endpoint = self._endpoints[key]
        except KeyError:
            raise LookupError(
                f"peripheral not registered: {key.kind}/{key.capability}"
            ) from None
        return cast("P", endpoint)

    def bind_workers[P: PeripheralStatus](
        self, key: PeripheralKey[P], workers: PeripheralWorkers
    ) -> None:
        """Bind a registered endpoint's workers once, after endpoint bootstrap."""
        self._require_mutable()
        self.require(key)
        if key in self._workers:
            raise ValueError(f"peripheral workers already bound: {key.kind}")
        self._workers[key] = workers

    def start(self) -> None:
        """Start bound workers in endpoint registration order."""
        workers = self._bound_workers()
        self._sealed = True
        for worker in workers:
            worker.start()

    def stop(self) -> None:
        """Stop bound workers in reverse endpoint registration order."""
        workers = self._bound_workers()
        self._sealed = True
        for worker in reversed(workers):
            worker.stop()

    def _bound_workers(self) -> tuple[PeripheralWorkers, ...]:
        if self._endpoints.keys() != self._workers.keys():
            raise LookupError("peripheral workers are not bound for every endpoint")
        return tuple(self._workers[key] for key in self._endpoints)

    def _require_mutable(self) -> None:
        if self._sealed:
            raise RuntimeError("peripheral registration is frozen")
