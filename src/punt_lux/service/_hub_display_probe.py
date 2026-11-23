"""Read the Display's own identity over the Hub's existing facts route."""

from __future__ import annotations

import http.client

from punt_lux.kernel.hub_paths import HubPaths
from punt_lux.operations.models.display_info import DisplayInfo


class HubDisplayProbe:
    """Use anonymous, read-only GET /display without a client-layer dependency."""

    @staticmethod
    def connected(pid: int, timeout: float) -> bool:
        """Require a successful Hub round trip to this exact Display process."""
        port = HubPaths().read_port()
        if port is None:
            raise ConnectionError(
                "Hub is not running; start it before restarting Display"
            )
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            connection.request("GET", "/display")
            response = connection.getresponse()
            return HubDisplayProbe._matches(response, pid)
        except TimeoutError:
            return False
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise ConnectionError(f"Hub Display probe unavailable: {error}") from error
        finally:
            connection.close()

    @staticmethod
    def _matches(response: http.client.HTTPResponse, pid: int) -> bool:
        if response.status in (503, 504):
            return False
        if response.status != 200:
            raise ConnectionError(f"Hub Display probe returned HTTP {response.status}")
        body = response.read(65536)
        return DisplayInfo.model_validate_json(body).pid == pid
