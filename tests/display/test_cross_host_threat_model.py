"""Threat-model regression tests: T1, T3, T4, T6 (DES-090 W13).

Each test encodes one row of system.tex §"Threat Model" as a concrete attack
scenario and asserts the defense holds -- a test that fails if the defense is
removed (fidelity), not merely that the happy path works. The adversary is the
one the threat model names: someone on the network path who is *not* the user
(another LAN device, a compromised host, an opportunistic scanner), attempting
either without valid credentials or with a credential stolen from one enrolled
machine. Every scenario runs over a real ``ssl.SSLContext`` handshake on TCP
loopback with real W7 trust material -- these are boundary tests, not mocks.

Threat rows covered here (system.tex §"Threat Model"):

* **T1** -- Connect and speak the Hub protocol at all. Defended by the mTLS
  handshake: an untrusted-CA or no-certificate peer fails closed before any
  application byte is read (``CrossHostListener`` + ``verify_mode=CERT_REQUIRED``).
* **T3** -- Inject content attributed to a real, already-connected Hub.
  Defended by certificate possession: a peer cannot present another Hub's
  private key, and cannot pair that Hub's public certificate with its own key.
  Gate 2 (``CrossHostVerification``) additionally refuses a validly-enrolled
  peer that declares a *different* Hub's identity.
* **T4** -- Cause a collision in the Display's per-``HubId`` stores by claiming
  an already-live hostname. Defended by the trust fork's resolution
  (§"Resolving the Trust Fork"): the hostname is derived from the peer
  certificate's SAN, never the self-reported ``HubId``, so a foreign cert
  declaring a live hostname is rejected before it can register.
* **T6** -- Downgrade the connection to an unauthenticated or unencrypted one.
  Defended by the listener never falling back to plaintext and by the TLS 1.3
  floor: a plaintext peer is bounded and dropped, a TLS 1.2 peer is refused.

Two defenses whose full realization is W10's wiring are out of scope here and
noted, not tested: rejection of a cross-host ``kind="test"`` connection, and the
``identity_guard`` content gate on a promoted TLS fd. Those gate a connection
*after* the handshake this suite exercises; W13 tests what is defensible today.
"""

from __future__ import annotations

import socket
import ssl
from typing import TYPE_CHECKING

import pytest

from punt_lux.display.cross_host_verification import CrossHostVerification
from punt_lux.domain.identity import HubId, HubScopedKey, HubScopedStore
from punt_lux.trust import CertificateAuthority
from tests.display._mtls_harness import FakeClock, LoopbackListener, MtlsMaterial

if TYPE_CHECKING:
    from pathlib import Path


class TestT1ConnectAtAll:
    """T1: connect and speak the Hub protocol at all.

    system.tex §"Threat Model": *"No -- TLS handshake fails closed before any
    application byte is read."* The connection is dropped, never promoted into
    the ordinary reader set where a ``recv`` could read a Hub message.
    """

    def test_t1_a_foreign_ca_peer_never_speaks_the_protocol(
        self, tmp_path: Path
    ) -> None:
        """An attacker with a cert from a CA this Display never trusts is
        dropped at the handshake -- no valid credential, no connection.

        The server-side drop is the invariant under test. This attacker trusts
        the Display's genuine server cert, so its own ``connect()`` completes its
        half and the rejection surfaces only server-side (a TLS record-timing
        detail the listener does not control) -- so the authoritative signal is
        the listener's ready/pending state, not the client's exception.
        """
        material = MtlsMaterial(tmp_path)
        listener = LoopbackListener.serving(material.server_context())
        foreign_ca = CertificateAuthority.create()  # never in the Display's anchor
        attacker_ctx = material.foreign_client_context(
            foreign_ca, "attacker.example.com"
        )
        connect = listener.connect(attacker_ctx)
        try:
            ready = listener.pump_until_ready_or_dropped()
            connect.join()
            assert not connect.is_alive()
            assert ready == []  # never promoted -- no application byte reachable
            assert listener.pending_count == 0  # dropped, not stuck pending
        finally:
            connect.close()
            listener.shutdown()

    def test_t1_a_no_certificate_peer_never_speaks_the_protocol(
        self, tmp_path: Path
    ) -> None:
        """A peer offering no client certificate is rejected -- mutual auth is
        not optional (``verify_mode=CERT_REQUIRED``)."""
        material = MtlsMaterial(tmp_path)
        listener = LoopbackListener.serving(material.server_context())
        connect = listener.connect(material.no_cert_client_context())
        try:
            ready = listener.pump_until_ready_or_dropped()
            connect.join()
            assert not connect.is_alive()
            assert ready == []
            assert listener.pending_count == 0
        finally:
            connect.close()
            listener.shutdown()

    def test_t1_fidelity_removing_cert_required_would_admit_a_no_cert_peer(
        self, tmp_path: Path
    ) -> None:
        """Fidelity control -- what breaks if the defense is removed.

        The identical no-certificate peer that
        :meth:`test_t1_a_no_certificate_peer_never_speaks_the_protocol` proves
        is dropped becomes *admitted* the moment ``CERT_REQUIRED`` is downgraded
        to ``CERT_NONE``. This proves the production ``verify_mode`` is
        load-bearing, not incidental: strip it and T1 reopens.
        """
        material = MtlsMaterial(tmp_path)
        listener = LoopbackListener.serving(material.defense_removed_server_context())
        connect = listener.connect(material.no_cert_client_context())
        try:
            ready = listener.pump_until_ready_or_dropped()
            connect.join()
            assert not connect.is_alive()
            assert len(ready) == 1  # defense removed -> the no-cert peer is admitted
            ready[0].close()
        finally:
            connect.close()
            listener.shutdown()


class TestT3InjectAsAnotherHub:
    """T3: inject content attributed to a real, already-connected Hub.

    system.tex §"Threat Model": *"No -- cannot present that Hub's private key"*
    and *"a stolen credential impersonates only the credential's own Hub."*
    """

    def test_t3_a_stolen_public_cert_cannot_be_paired_with_a_foreign_key(
        self, tmp_path: Path
    ) -> None:
        """A certificate is public and can be sniffed; the private key is not.

        An adversary holding a live Hub's *certificate* but only its own,
        different, private key cannot assemble a usable credential: OpenSSL
        refuses to pair a certificate with a key whose public half it does not
        match. The matching key, by contrast, loads cleanly -- proving the
        rejection is specifically the missing private key, not a malformed cert.
        """
        material = MtlsMaterial(tmp_path)
        hub_key, hub_leaf = material.issue("hub1.example.com")
        attacker_key, attacker_leaf = material.issue("attacker.example.com")
        hub_cert_path, hub_key_path = material.write_pair(hub_key, hub_leaf)
        _, attacker_key_path = material.write_pair(attacker_key, attacker_leaf)

        with pytest.raises(ssl.SSLError):
            material.bare_client_context().load_cert_chain(
                str(hub_cert_path), str(attacker_key_path)
            )

        # Control: the genuine key-holder pairs the same cert without error.
        material.bare_client_context().load_cert_chain(
            str(hub_cert_path), str(hub_key_path)
        )

    def test_t3_a_foreign_hub_cannot_attribute_content_to_another_hub(
        self, tmp_path: Path
    ) -> None:
        """A legitimately-enrolled Hub cannot speak as a *different* Hub.

        The attacker's own certificate is valid -- Gate 1 (the mTLS handshake)
        authenticates it -- but when it declares a ``HubId`` naming another
        machine, Gate 2 refuses: the verified hostname comes from the cert's
        SAN, not the self-reported identity. A stolen or self-issued credential
        can only ever act as its own Hub.
        """
        material = MtlsMaterial(tmp_path)
        listener = LoopbackListener.serving(material.server_context())
        attacker_ctx = material.trusted_client_context("attacker.example.com")
        connect = listener.connect(attacker_ctx)
        try:
            ready = listener.pump_until_ready_or_dropped()
            connect.join()
            assert not connect.is_alive()
            assert len(ready) == 1  # Gate 1 authenticated the attacker's own cert
            server_sock = ready[0]
            try:
                verification = CrossHostVerification()
                # Declaring hub1's identity -- attributing content to it -- is refused.
                assert (
                    verification.reject_unless_verified(
                        server_sock, HubId("hub1.example.com", 4242)
                    )
                    is True
                )
                # Declaring its own true identity is accepted (control).
                assert (
                    verification.reject_unless_verified(
                        server_sock, HubId("attacker.example.com", 4242)
                    )
                    is False
                )
            finally:
                server_sock.close()
        finally:
            connect.close()
            listener.shutdown()


class TestT4StoreCollision:
    """T4: collide in the Display's per-``HubId`` stores via a claimed hostname.

    system.tex §"Threat Model": *"No -- hostname is cert-verified, not
    self-reported"* (§"Resolving the Trust Fork").
    """

    def test_t4_claiming_a_live_hostname_with_a_foreign_cert_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """The attacker's declared hostname *equals* an already-live Hub's, so
        it would land on the identical ``HubScopedKey`` and clobber that Hub's
        store slot -- yet Gate 2 rejects it before it can register, because the
        cert SAN (``attacker.example.com``) is not the claimed ``hub1``.
        """
        material = MtlsMaterial(tmp_path)
        listener = LoopbackListener.serving(material.server_context())
        attacker_ctx = material.trusted_client_context("attacker.example.com")
        connect = listener.connect(attacker_ctx)
        try:
            ready = listener.pump_until_ready_or_dropped()
            connect.join()
            assert not connect.is_alive()
            assert len(ready) == 1
            server_sock = ready[0]
            try:
                live_hub = HubId("hub1.example.com", 111)
                collider = HubId("hub1.example.com", 111)  # the slot it would clobber
                assert HubScopedKey(collider, "scene-1") == HubScopedKey(
                    live_hub, "scene-1"
                )
                verification = CrossHostVerification()
                assert (
                    verification.reject_unless_verified(server_sock, collider) is True
                )
            finally:
                server_sock.close()
        finally:
            connect.close()
            listener.shutdown()

    def test_t4_fidelity_a_self_reported_hostname_collides_in_the_store(self) -> None:
        """Fidelity control -- what breaks if the defense is removed.

        Were the hostname taken from the wire (the self-reported ``HubId``)
        rather than the certificate's SAN, an attacker declaring a live Hub's
        hostname would be indistinguishable from it and would clobber its store
        entry. This shows the collision Gate 2 exists to prevent: two distinct
        machines, one declared identity, one store slot.
        """
        store: HubScopedStore[str] = HubScopedStore()
        live_hub = HubId("hub1.example.com", 4242)
        store.put(HubScopedKey(live_hub, "scene-1"), "hub1's content")

        # The trust fork's failure mode: the attacker's self-report is trusted.
        # Even a differently-cased claim canonicalizes to the same identity.
        self_reported = HubId("HUB1.EXAMPLE.COM", 4242)
        assert self_reported == live_hub  # indistinguishable by self-report alone

        store.put(HubScopedKey(self_reported, "scene-1"), "attacker's content")

        assert len(store) == 1  # no second entry -- hub1's slot was overwritten
        assert store.get(HubScopedKey(live_hub, "scene-1")) == "attacker's content"


class TestT6Downgrade:
    """T6: downgrade the connection to an unauthenticated or unencrypted one.

    system.tex §"Threat Model": *"No -- the cross-host listener never accepts
    ``kind="test"`` and never falls back to plaintext."* The ``kind="test"``
    half is W10's admission wiring; tested here is the plaintext/version floor,
    which is defensible at the transport today.
    """

    def test_t6_a_plaintext_peer_is_bounded_and_dropped_never_promoted(
        self, tmp_path: Path
    ) -> None:
        """A raw TCP peer that speaks no TLS -- sending a plaintext Hub-looking
        line instead of a ``ClientHello`` -- is never interpreted as a Hub
        connection. Its bytes drive no fallback path; it is dropped, either as a
        failed handshake or, if it stalls mid-record, at its bounded deadline.
        The deadline reads an injected :class:`FakeClock`, so the drop is
        asserted deterministically rather than by racing the wall clock.
        """
        material = MtlsMaterial(tmp_path)
        clock = FakeClock()
        listener = LoopbackListener.with_clock(
            material.server_context(), handshake_budget=0.05, clock=clock
        )
        plaintext_peer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            plaintext_peer.connect(("127.0.0.1", listener.port))
            plaintext_peer.sendall(b'{"kind": "connect"}\n')  # not a TLS ClientHello

            listener.accept_pending()
            assert listener.pending_count == 1  # accepted to pending, NOT promoted

            assert listener.pump_ready() == []  # never falls back to plaintext
            clock.advance(0.1)  # past the 0.05s budget, if it stalled mid-record
            assert listener.pump_ready() == []
            assert listener.pending_count == 0  # dropped: failed or deadline-expired
        finally:
            plaintext_peer.close()
            listener.shutdown()

    def test_t6_a_tls12_only_peer_is_refused_by_the_13_floor(
        self, tmp_path: Path
    ) -> None:
        """A peer offering only TLS 1.2 -- a version downgrade -- is refused by
        the Display's ``minimum_version=TLSv1_3`` floor, even though its
        certificate is otherwise valid. There is no downgrade to a weaker
        protocol.
        """
        material = MtlsMaterial(tmp_path)
        listener = LoopbackListener.serving(material.server_context())
        downgrade_ctx = material.downgrade_client_context("hub1.example.com")
        connect = listener.connect(downgrade_ctx)
        try:
            ready = listener.pump_until_ready_or_dropped()
            connect.join()
            assert not connect.is_alive()
            assert ready == []  # the 1.3 floor refuses the 1.2 downgrade
            assert listener.pending_count == 0
            assert connect.handshake_failed()
        finally:
            connect.close()
            listener.shutdown()
