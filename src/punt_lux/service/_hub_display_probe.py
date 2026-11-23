"""Read the Display's own identity over the Hub's existing facts route."""

from __future__ import annotations

import http.client

from punt_lux.kernel.hub_paths import HubPaths
from punt_lux.service._hub_display_facts import HubDisplayFacts


class HubDisplayProbe:
    """Use anonymous, read-only GET /display without a client-layer dependency."""

    @staticmethod
    def connected(pid: int, timeout: float) -> str | None:
        """Require a successful Hub round trip to this exact Display process."""
        port = HubDisplayProbe._port()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            connection.request("GET", "/display")
            response = connection.getresponse()
            return HubDisplayFacts.identity(response, pid)
        except TimeoutError:
            return None
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise ConnectionError(f"Hub Display probe unavailable: {error}") from error
        finally:
            connection.close()

    @staticmethod
    def _port() -> int:
        port = HubPaths().read_port()
        if port is None:
            raise ConnectionError(
                "Hub is not running; start it before restarting Display"
            )
        return port
