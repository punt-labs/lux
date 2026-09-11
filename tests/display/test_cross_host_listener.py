"""CrossHostListener -- accept/handshake/deadline/drop over real TCP+TLS.

Drives a real ``ssl.SSLContext`` handshake over TCP loopback with material
from ``punt_lux.trust`` (W7) rather than asserting on ``cryptography``
objects alone -- OpenSSL's handshake is what actually proves the extension
set and the AuthorityKeyIdentifier chain are correct (system.tex
§"Trust Anchor Providers"). The client side of every handshake runs on a
background thread: a blocking client ``connect()`` performs its TLS
handshake synchronously and needs a concurrently-pumped server on the
other end, exactly as a real Hub's connect would meet the Display's
non-blocking, per-frame-pumped accept loop.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

import pytest

from punt_lux.display.cross_host_listener import CrossHostListener
from punt_lux.trust import CertificateAuthority

if TYPE_CHECKING:
    from punt_lux.trust import KeyPair, LeafCertificate


@final
class _FakeClock:
    """A deterministic, test-advanced substitute for ``time.monotonic``.

    Deadline math (``pump_ready``'s expiry check, ``accept_pending``'s
    deadline stamp) reads this instead of the wall clock, so a deadline
    test asserts state transitions the test itself controls rather than
    racing real ``time.sleep`` against real elapsed time.
    """

    _now: float
    __slots__ = ("_now",)

    def __new__(cls, start: float = 1_000.0) -> Self:
        self = super().__new__(cls)
        self._now = start
        return self

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ---------------------------------------------------------------------------
# Helpers -- real mTLS material over TCP loopback
# ---------------------------------------------------------------------------


def _server_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    """Build the Display's server-side context: requires a client cert
    signed by ``ca``, and presents its own leaf for that same CA."""
    context = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.CLIENT_AUTH)
    key_pair, leaf = ca.issue_leaf("display.example.com")
    cert_path, key_path = tmp_path / "server.crt", tmp_path / "server.key"
    cert_path.write_bytes(leaf.to_pem())
    key_path.write_bytes(key_pair.to_pem())
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def _client_context(
    ca: CertificateAuthority, tmp_path: Path, leaf: tuple[KeyPair, LeafCertificate]
) -> ssl.SSLContext:
    """Build a Hub's client-side context: verifies the Display's leaf against
    ``ca`` and presents its own ``leaf`` for mutual authentication."""
    context = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False  # loopback test host never matches a SAN
    key_pair, cert = leaf
    cert_path, key_path = tmp_path / "client.crt", tmp_path / "client.key"
    cert_path.write_bytes(cert.to_pem())
    key_path.write_bytes(key_pair.to_pem())
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def _no_cert_client_context(ca: CertificateAuthority) -> ssl.SSLContext:
    """A client context that verifies the server but presents no certificate."""
    context = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False
    return context


def _connect_in_background(
    ctx: ssl.SSLContext, port: int
) -> tuple[threading.Thread, list[ssl.SSLSocket | BaseException]]:
    """Run a blocking client TLS connect on a background thread.

    A client-side ``connect()`` performs its handshake synchronously and
    blocks until the server responds, so it must run concurrently with the
    server's own non-blocking accept/pump loop rather than before it.
    Returns the thread and a one-element result list the caller polls: the
    connected socket on success, or the raised exception on failure/reset.
    """
    result: list[ssl.SSLSocket | BaseException] = []

    def _run() -> None:
        try:
            client = ctx.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            client.connect(("127.0.0.1", port))
            result.append(client)
        except (OSError, ssl.SSLError) as exc:
            result.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread, result


def _pump_until_ready_or_dropped(
    listener: CrossHostListener, *, rounds: int = 400, delay: float = 0.005
) -> list[ssl.SSLSocket]:
    """Drive accept/pump for up to ``rounds`` frames; return newly-ready sockets.

    Mirrors the render loop's own per-frame cadence (accept, then pump, once
    per iteration). Stops early once nothing is pending and nothing became
    ready -- the connecting client either succeeded, was rejected, or has
    not reached the listener yet.
    """
    for _ in range(rounds):
        listener.accept_pending()
        ready = listener.pump_ready()
        if ready:
            return ready
        if listener.pending_count == 0:
            time.sleep(delay)  # give a not-yet-arrived connect another chance
        time.sleep(delay)
    return []


def _free_port() -> int:
    """Return an ephemeral port the OS has not yet assigned to anyone else."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSetup:
    def test_setup_binds_and_listens(self, tmp_path: Path) -> None:
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        try:
            listener.setup("127.0.0.1", _free_port())
            assert listener.server_sock is not None
        finally:
            listener.shutdown()

    def test_setup_propagates_a_real_bind_failure(self, tmp_path: Path) -> None:
        """A port already bound by another socket fails loud, not silently."""
        ca = CertificateAuthority.create()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = int(blocker.getsockname()[1])
        listener = CrossHostListener(_server_context(ca, tmp_path))
        try:
            with pytest.raises(OSError):
                listener.setup("127.0.0.1", port)
            assert listener.server_sock is None
        finally:
            blocker.close()
            listener.shutdown()

    def test_setup_closes_a_prior_listening_socket_before_rebinding(
        self, tmp_path: Path
    ) -> None:
        """A second setup() must not leave the first socket bound and exposed
        underneath the new one -- it closes the old fd first."""
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        try:
            listener.setup("127.0.0.1", _free_port())
            first_sock = listener.server_sock
            assert first_sock is not None
            assert first_sock.fileno() >= 0

            listener.setup("127.0.0.1", _free_port())

            assert first_sock.fileno() == -1  # the old socket was actually closed
            assert listener.server_sock is not None
            assert listener.server_sock is not first_sock
        finally:
            listener.shutdown()


class TestHandshakeSuccess:
    def test_a_valid_client_certificate_completes_the_handshake(
        self, tmp_path: Path
    ) -> None:
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        client_ctx = _client_context(ca, tmp_path, ca.issue_leaf("hub1.example.com"))
        try:
            port = _free_port()
            listener.setup("127.0.0.1", port)
            thread, result = _connect_in_background(client_ctx, port)
            try:
                ready = _pump_until_ready_or_dropped(listener)
                thread.join(timeout=5.0)
                assert not thread.is_alive()
                assert len(ready) == 1
                assert listener.pending_count == 0
                assert result and isinstance(result[0], ssl.SSLSocket)
            finally:
                if result and isinstance(result[0], ssl.SSLSocket):
                    result[0].close()
        finally:
            listener.shutdown()

    def test_the_pending_set_is_empty_once_no_connection_is_outstanding(
        self, tmp_path: Path
    ) -> None:
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        try:
            listener.setup("127.0.0.1", _free_port())
            listener.accept_pending()  # nothing connected -- must not block or raise
            assert listener.pending_count == 0
            assert listener.pump_ready() == []
        finally:
            listener.shutdown()


class TestHandshakeRejection:
    def test_a_client_certificate_from_an_untrusted_ca_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """T1: no application byte is ever read from an unverified peer --
        the connection is dropped, never promoted to the ready set."""
        ca = CertificateAuthority.create()
        other_ca = CertificateAuthority.create()  # a different, untrusted CA
        listener = CrossHostListener(_server_context(ca, tmp_path))
        client_ctx = _client_context(
            other_ca, tmp_path, other_ca.issue_leaf("attacker.example.com")
        )
        try:
            port = _free_port()
            listener.setup("127.0.0.1", port)
            thread, result = _connect_in_background(client_ctx, port)
            try:
                ready = _pump_until_ready_or_dropped(listener)
                thread.join(timeout=5.0)
                assert not thread.is_alive()
                assert ready == []
                assert listener.pending_count == 0  # dropped, not stuck pending
                assert result and isinstance(result[0], BaseException)
            finally:
                if result and isinstance(result[0], ssl.SSLSocket):
                    result[0].close()
        finally:
            listener.shutdown()

    def test_a_client_offering_no_certificate_is_rejected(self, tmp_path: Path) -> None:
        """``verify_mode=CERT_REQUIRED`` on the server context enforces this --
        mutual auth is not optional (system.tex "Transport Specification").

        The server-side rejection (asserted below) is the invariant under
        test. Whether the client's own ``connect()`` sees the abort as an
        immediate ``SSLError`` or completes and only fails on first use is a
        client-side TLS record-timing detail, not something this listener
        controls or this test asserts on.
        """
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        client_ctx = _no_cert_client_context(ca)
        try:
            port = _free_port()
            listener.setup("127.0.0.1", port)
            thread, result = _connect_in_background(client_ctx, port)
            try:
                ready = _pump_until_ready_or_dropped(listener)
                thread.join(timeout=5.0)
                assert not thread.is_alive()
                assert ready == []
                assert listener.pending_count == 0  # dropped server-side, never ready
            finally:
                if result and isinstance(result[0], ssl.SSLSocket):
                    result[0].close()
        finally:
            listener.shutdown()


class TestBoundedDeadline:
    def test_a_stalled_peer_is_dropped_at_its_deadline_not_blocked(
        self, tmp_path: Path
    ) -> None:
        """The fail-closed backstop (T1's opportunistic scanner): a peer that
        completes the TCP handshake and sends nothing is dropped once its
        budget expires. The deadline reads an injected ``_FakeClock``, not
        the wall clock -- the test advances time deterministically instead
        of racing a real ``time.sleep`` against real elapsed time.
        """
        ca = CertificateAuthority.create()
        clock = _FakeClock()
        listener = CrossHostListener(
            _server_context(ca, tmp_path), handshake_budget=0.05, clock=clock
        )
        try:
            port = _free_port()
            listener.setup("127.0.0.1", port)
            stalled = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            stalled.connect(("127.0.0.1", port))  # TCP connects; no TLS bytes ever sent
            try:
                listener.accept_pending()
                assert listener.pending_count == 1

                # The clock hasn't moved: still well before the budget.
                ready = listener.pump_ready()
                assert ready == []
                assert listener.pending_count == 1

                clock.advance(0.1)  # deterministically past the 0.05s budget
                ready = listener.pump_ready()
                assert ready == []
                assert listener.pending_count == 0  # dropped, not left dangling
            finally:
                stalled.close()
        finally:
            listener.shutdown()


class TestPendingCap:
    def test_a_peer_over_the_cap_is_refused_not_queued(self, tmp_path: Path) -> None:
        """Admission control against a handshake-flood burst: once the
        pending set is at ``max_pending``, a newly-accepted peer is refused
        (closed) immediately rather than growing the set further.
        """
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path), max_pending=1)
        try:
            port = _free_port()
            listener.setup("127.0.0.1", port)
            first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            first.connect(("127.0.0.1", port))
            second.connect(("127.0.0.1", port))
            try:
                listener.accept_pending()  # admits the first -- fills the cap
                assert listener.pending_count == 1

                listener.accept_pending()  # the second is refused, not queued
                assert listener.pending_count == 1
            finally:
                first.close()
                second.close()
        finally:
            listener.shutdown()


class TestShutdown:
    def test_shutdown_closes_the_listening_and_pending_sockets(
        self, tmp_path: Path
    ) -> None:
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        port = _free_port()
        listener.setup("127.0.0.1", port)
        stalled = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stalled.connect(("127.0.0.1", port))
        try:
            listener.accept_pending()
            assert listener.pending_count == 1
        finally:
            stalled.close()

        listener.shutdown()

        assert listener.server_sock is None
        assert listener.pending_count == 0
