"""A real mTLS-over-loopback rig shared by the cross-host boundary tests.

These are real boundary tests, not mocks: a real ``ssl.SSLContext`` handshake
runs over TCP loopback with material issued by ``punt_lux.trust`` (W7), because
OpenSSL's own handshake is what actually proves the extension set, the trust
chain, and the TLS-version floor -- asserting on ``cryptography`` objects alone
would not (system.tex §"Trust Anchor Providers"). The threat-model regression
suite (``test_cross_host_threat_model.py``) drives every scenario through this
one rig so an adversarial client is constructed the same faithful way a real
Hub's connect is, differing only in the one property under attack.

The rig is three small collaborators, each owning one concern:

* :class:`MtlsMaterial` -- a personal CA and the leaf/context factory. It mints
  both honest and adversarial ``ssl.SSLContext`` shapes: a trusted client, a
  client from a foreign (untrusted) CA, a client presenting no certificate, a
  client that will only speak TLS 1.2, and -- for a fidelity control -- a server
  context with the mutual-auth requirement deliberately stripped.
* :class:`LoopbackListener` -- a :class:`CrossHostListener` bound to a loopback
  ephemeral port, pumped on the render loop's own per-frame cadence.
* :class:`BackgroundConnect` -- a client TLS connect on its own thread, whose
  outcome the caller polls; a blocking ``connect()`` performs its handshake
  synchronously and needs a concurrently-pumped server on the other end.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.cross_host_listener import CrossHostListener
from punt_lux.trust import CertificateAuthority

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_lux.trust import KeyPair, LeafCertificate

__all__ = [
    "BackgroundConnect",
    "FakeClock",
    "LoopbackListener",
    "MtlsMaterial",
]

_DISPLAY_HOST = "display.example.com"


@final
class FakeClock:
    """A deterministic, test-advanced substitute for ``time.monotonic``.

    A deadline test that advances this clock asserts a state transition it
    controls, rather than racing a real ``time.sleep`` against real elapsed
    wall-clock time.
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
        """Move the clock forward by *seconds* (monotonic units)."""
        self._now += seconds


@final
class MtlsMaterial:
    """A personal CA plus the leaf/context factory the rig authenticates against.

    Owns one :class:`CertificateAuthority` -- the Display's trust anchor -- and
    a scratch directory for the PEM files ``ssl.SSLContext.load_cert_chain``
    reads (the stdlib has no in-memory chain-loading API). Every context this
    mints, honest or adversarial, is built from that one anchor so the only
    thing that varies between an accepted peer and a rejected one is the exact
    property the corresponding threat attacks.
    """

    _ca: CertificateAuthority
    _dir: Path
    _seq: int
    __slots__ = ("_ca", "_dir", "_seq")

    def __new__(cls, scratch_dir: Path, ca: CertificateAuthority | None = None) -> Self:
        self = super().__new__(cls)
        self._ca = ca if ca is not None else CertificateAuthority.create()
        self._dir = scratch_dir
        self._seq = 0
        return self

    @property
    def ca(self) -> CertificateAuthority:
        """The CA whose leaves this Display's trust anchor verifies."""
        return self._ca

    def server_context(self) -> ssl.SSLContext:
        """The Display's server side: requires a client cert signed by our CA,
        and presents its own leaf for the same CA (production path).
        """
        context = self._ca.trust_anchor().build_ssl_context(
            purpose=ssl.Purpose.CLIENT_AUTH
        )
        self._load_leaf(context, *self._ca.issue_leaf(_DISPLAY_HOST))
        return context

    def trusted_client_context(self, hostname: str) -> ssl.SSLContext:
        """A Hub legitimately enrolled with our CA, cert SAN naming *hostname*."""
        return self._client_context(self._ca, hostname)

    def foreign_client_context(
        self, foreign_ca: CertificateAuthority, hostname: str
    ) -> ssl.SSLContext:
        """A Hub whose cert *foreign_ca* signed -- a CA this Display never trusts."""
        return self._client_context(foreign_ca, hostname)

    def no_cert_client_context(self) -> ssl.SSLContext:
        """A client that verifies the Display but presents no certificate of its
        own -- the mutual half of mutual auth deliberately omitted.
        """
        context = self._ca.trust_anchor().build_ssl_context(
            purpose=ssl.Purpose.SERVER_AUTH
        )
        context.check_hostname = False  # loopback host never matches a SAN
        return context

    def downgrade_client_context(self, hostname: str) -> ssl.SSLContext:
        """A client that will only speak TLS 1.2 -- the downgrade a T6 adversary
        attempts against the Display's 1.3 floor.

        Built directly rather than through ``build_ssl_context`` precisely
        because that helper pins the 1.3 minimum this context must undercut to
        exercise the server's floor at all.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cadata=self._anchor_pem())
        self._load_leaf(context, *self._ca.issue_leaf(hostname))
        return context

    def defense_removed_server_context(self) -> ssl.SSLContext:
        """A fidelity control: the Display's server context with the
        ``CERT_REQUIRED`` mutual-auth requirement stripped to ``CERT_NONE``.

        This is the exact defense removed. A test that admits a no-cert peer
        through *this* context, while the production :meth:`server_context`
        drops it, proves the production ``verify_mode`` is load-bearing rather
        than incidental.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_NONE
        self._load_leaf(context, *self._ca.issue_leaf(_DISPLAY_HOST))
        return context

    def bare_client_context(self) -> ssl.SSLContext:
        """A client context that verifies the Display but has not yet loaded any
        client credential -- the caller loads (or fails to load) one itself,
        for the T3 "a cert is not wieldable without its key" attack.
        """
        context = self._ca.trust_anchor().build_ssl_context(
            purpose=ssl.Purpose.SERVER_AUTH
        )
        context.check_hostname = False
        return context

    def issue(self, hostname: str) -> tuple[KeyPair, LeafCertificate]:
        """Issue a fresh keypair and CA-signed leaf naming *hostname*."""
        return self._ca.issue_leaf(hostname)

    def write_pair(self, key_pair: KeyPair, cert: LeafCertificate) -> tuple[Path, Path]:
        """Write *cert* and *key_pair* to unique scratch files; return their paths.

        Unique per call so one test can build several distinct credentials --
        a live Hub's and an attacker's -- without one clobbering the other.
        """
        self._seq += 1
        cert_path = self._dir / f"leaf-{self._seq}.crt"
        key_path = self._dir / f"leaf-{self._seq}.key"
        cert_path.write_bytes(cert.to_pem())
        key_path.write_bytes(key_pair.to_pem())
        return cert_path, key_path

    def _client_context(
        self, signing_ca: CertificateAuthority, hostname: str
    ) -> ssl.SSLContext:
        context = self._ca.trust_anchor().build_ssl_context(
            purpose=ssl.Purpose.SERVER_AUTH
        )
        context.check_hostname = False  # loopback host never matches a SAN
        self._load_leaf(context, *signing_ca.issue_leaf(hostname))
        return context

    def _load_leaf(
        self, context: ssl.SSLContext, key_pair: KeyPair, cert: LeafCertificate
    ) -> None:
        cert_path, key_path = self.write_pair(key_pair, cert)
        context.load_cert_chain(str(cert_path), str(key_path))

    def _anchor_pem(self) -> str:
        return self._ca.trust_anchor().bundle_pem().decode("ascii")


@final
class BackgroundConnect:
    """A client TLS connect running on its own thread; the caller polls its outcome.

    A client-side ``connect()`` performs its handshake synchronously and blocks
    until the server responds, so it must run concurrently with the server's own
    non-blocking, per-frame accept/pump loop rather than before it. The outcome
    is the connected socket on success, or the raised exception on failure/reset.
    """

    _thread: threading.Thread
    _result: list[ssl.SSLSocket | BaseException]
    __slots__ = ("_result", "_thread")

    def __new__(cls, context: ssl.SSLContext, port: int) -> Self:
        self = super().__new__(cls)
        self._result = []
        self._thread = threading.Thread(
            target=self._run, args=(context, port), daemon=True
        )
        self._thread.start()
        return self

    def _run(self, context: ssl.SSLContext, port: int) -> None:
        try:
            client = context.wrap_socket(
                socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            )
            client.connect(("127.0.0.1", port))
            self._result.append(client)
        except (OSError, ssl.SSLError) as exc:
            self._result.append(exc)

    def join(self, timeout: float = 5.0) -> None:
        """Wait for the connect thread to finish, up to *timeout* seconds."""
        self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        """Return whether the connect thread is still running."""
        return self._thread.is_alive()

    def handshake_failed(self) -> bool:
        """Return whether the client's own handshake ended in an exception.

        A client whose ``connect()`` raised never authenticated; note that a
        server-side rejection can also surface only on the client's first
        *use* of an apparently-connected socket, a TLS record-timing detail
        the server does not control -- so a ``False`` here is not by itself
        proof of admission. The authoritative signal is always the listener's
        own ready/pending state, which this method complements rather than
        replaces.
        """
        return bool(self._result) and isinstance(self._result[0], BaseException)

    def close(self) -> None:
        """Close the connected socket if the handshake produced one."""
        if self._result and isinstance(self._result[0], ssl.SSLSocket):
            self._result[0].close()


@final
class LoopbackListener:
    """A :class:`CrossHostListener` bound to a loopback ephemeral port.

    Wraps a caller-built listener (so a test can inject a short handshake budget
    and a :class:`FakeClock`) and drives it on the render loop's own per-frame
    cadence: accept, then pump, once per iteration.
    """

    _listener: CrossHostListener
    _port: int
    __slots__ = ("_listener", "_port")

    def __new__(cls, listener: CrossHostListener) -> Self:
        self = super().__new__(cls)
        self._listener = listener
        self._port = cls._free_port()
        listener.setup("127.0.0.1", self._port)
        return self

    @classmethod
    def serving(cls, server_context: ssl.SSLContext) -> Self:
        """Bind a default-parameter listener presenting *server_context*."""
        return cls(CrossHostListener(server_context))

    @classmethod
    def with_clock(
        cls,
        server_context: ssl.SSLContext,
        handshake_budget: float,
        clock: Callable[[], float],
    ) -> Self:
        """Bind a listener whose deadline reads *clock* on a *handshake_budget*."""
        return cls(
            CrossHostListener(
                server_context, handshake_budget=handshake_budget, clock=clock
            )
        )

    @property
    def port(self) -> int:
        """The loopback TCP port this listener is bound to."""
        return self._port

    @property
    def pending_count(self) -> int:
        """How many sockets are awaiting a completed handshake."""
        return self._listener.pending_count

    def connect(self, context: ssl.SSLContext) -> BackgroundConnect:
        """Start a background client TLS connect against this listener's port."""
        return BackgroundConnect(context, self._port)

    def accept_pending(self) -> None:
        """Accept any newly-connected peers into the pending-handshake set."""
        self._listener.accept_pending()

    def pump_ready(self) -> list[ssl.SSLSocket]:
        """Drive every pending handshake one step; return newly-verified sockets."""
        return self._listener.pump_ready()

    def pump_until_ready_or_dropped(
        self, *, rounds: int = 400, delay: float = 0.005
    ) -> list[ssl.SSLSocket]:
        """Pump accept/handshake for up to *rounds* frames; return ready sockets.

        Stops early once nothing is pending and nothing became ready -- the
        connecting client has either succeeded, been rejected, or not yet
        arrived; a short sleep gives a not-yet-arrived connect another chance.
        """
        for _ in range(rounds):
            self._listener.accept_pending()
            ready = self._listener.pump_ready()
            if ready:
                return ready
            if self._listener.pending_count == 0:
                time.sleep(delay)
            time.sleep(delay)
        return []

    def shutdown(self) -> None:
        """Close the listening socket and every pending (unverified) connection."""
        self._listener.shutdown()

    @staticmethod
    def _free_port() -> int:
        """Return an ephemeral loopback port the OS has not yet assigned."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])
