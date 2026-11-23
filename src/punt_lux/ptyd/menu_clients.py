"""One explicit daemon identity backs menu registration, scenes and listen leg."""

from __future__ import annotations

from typing import Self

from punt_lux.client.facade import LuxClient
from punt_lux.hub.client_identity import ClientIdentity
from punt_lux.hub_client import CallbackHandler, ConnectHandler, LuxHubClient


class TerminalClients:
    _identity: ClientIdentity

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._identity = ClientIdentity(kind="app", name="luxd-pty", lease_ttl=30)
        return self

    def client(self) -> LuxClient:
        return LuxClient.for_identity(self._identity)

    def listener(
        self,
        callback: CallbackHandler,
        connected: ConnectHandler,
    ) -> LuxHubClient:
        return self.client().listener(
            on_callback=callback,
            on_connect=connected,
            on_event=self._ignore,
        )

    @staticmethod
    def _ignore(_topic: str, _payload: object) -> None:
        """No topic subscriptions belong to this launcher."""
