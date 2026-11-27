"""The names the library guide tells a service provider to import are importable."""

from __future__ import annotations

import punt_lux.client as client_package


def test_the_service_accessor_and_the_refusal_error_are_public() -> None:
    assert "ServiceAccessor" in client_package.__all__
    assert "RequestRefusedError" in client_package.__all__
    assert client_package.ServiceAccessor.__name__ == "ServiceAccessor"
    assert issubclass(client_package.RequestRefusedError, Exception)
