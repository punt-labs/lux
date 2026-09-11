"""_AcmPcaClient — the structural interface Provider 2 (AWS Private CA) needs.

Two ``runtime_checkable`` Protocols, not base classes, per the org's
"families share via Protocol" standard: ``boto3.client("acm-pca")``
satisfies both by having the named methods — boto3 clients are generated
dynamically from AWS's service model, not declared in source, so nothing
here imports or subclasses boto3. A typed in-repo test fake satisfies the
identical contract without touching AWS at all. Each Protocol states only
the keyword shape :mod:`.aws_private_ca_provider` actually sends, not
boto3's full untyped surface for this service.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

__all__ = ["_AcmPcaClient", "_Boto3Module"]


class _Boto3Module(Protocol):
    """The one ``boto3`` module member :meth:`.AwsPrivateCaProvider.connect`
    calls — typed so casting the untyped ``boto3`` import onto it, once,
    resolves every downstream type cleanly instead of needing a
    ``# pyright: ignore`` at the call site.
    """

    def client(
        self, service_name: Literal["acm-pca"], *, region_name: str | None = None
    ) -> object:
        """Return a boto3 low-level client for *service_name*."""
        ...


@runtime_checkable
class _AcmPcaWaiter(Protocol):
    """A boto3 waiter — blocks until ACM Private CA finishes issuing."""

    def wait(self, **kwargs: str) -> None:
        """Poll until the awaited condition holds, or raise on timeout."""
        ...


@runtime_checkable
class _AcmPcaClient(Protocol):
    """The subset of ``boto3.client("acm-pca")`` Provider 2 calls."""

    def issue_certificate(self, **kwargs: object) -> dict[str, str]:
        """Request a leaf certificate; returns the pending ``CertificateArn``."""
        ...

    def get_certificate(self, **kwargs: str) -> dict[str, str]:
        """Return the issued ``Certificate`` (and ``CertificateChain``)."""
        ...

    def get_certificate_authority_certificate(self, **kwargs: str) -> dict[str, str]:
        """Return the CA's own ``Certificate`` and ``CertificateChain``."""
        ...

    def get_waiter(self, waiter_name: Literal["certificate_issued"]) -> _AcmPcaWaiter:
        """Return a waiter that blocks until the named condition holds."""
        ...
