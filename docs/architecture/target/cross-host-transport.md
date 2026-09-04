# Lux Cross-Host Transport and Trust

**Status:** canonical target for the cross-host Hub&harr;Display transport
and trust model.
**Ratifies:** DES-090 in `DESIGN.md`.
**Depends on:** [addressing.md](./addressing.md) (DES-089) — that document
specifies the identity ladder and states, in its "Dependencies on the
cross-host transport layer" section, the five-point contract this document
satisfies. Read that section first. This document does not redefine the
addressing model (`Rung`, `LuxAddress`, `AddressBook`, `HubId`'s two fields);
it specifies how a `HubId` gets to the Display safely once more than one
machine is involved.

## Problem

Today the Hub-to-Display leg is a single mechanism doing two jobs at once:
`AF_UNIX`, mode `0700`, one well-known path per user
(`display/socket_server.py`, `paths.py`). The socket's filesystem permission
*is* the entire trust model — anything that can open the path is, by
construction, a process the same OS user already controls. `transport_policy.py`
states the analogous refusal explicitly for luxd's other leg (MCP/REST):
`LoopbackTransportPolicy.allows_bind_host` rejects any bind host outside
`127.0.0.1`/`localhost`, because "an off-loopback bind needs authentication and
a bind-derived origin policy that this unit does not carry." The Hub-to-Display
leg has never had an analogous policy stated, because it has never needed
one — cross-host is exactly what gives it a reason to.

The operator ruled (2026-09-04) that a single user's Display may aggregate
Hubs running on other machines, now, not deferred. That breaks the one
assumption the whole trust model rests on: "whoever can reach this socket is
already this user." A network socket has no equivalent free lunch — anyone
who can route a TCP packet to the Display's port can attempt to speak the Hub
protocol to it, and nothing about `AF_UNIX`'s trust argument carries over.
This document specifies what replaces it.

## Scope boundary

This document owns: the network transport, who initiates a connection and how
the endpoint is known, the authentication and trust mechanism, and how
connect/reconnect/disconnect map onto the Display's existing fd-scoped
ownership and preemption machinery. It does **not** own: the addressing model
(rungs, `LuxAddress`, `AddressBook`, per-store `HubId` keying — see
addressing.md), and it does not own DES-086's connection-scoped read/write
security boundary (see "Reconciliation," below) — this document extends that
boundary to a new transport, it does not alter it.

**One direction only.** The Hub is, in both the same-host and cross-host
cases, the connecting party — it dials the Display, never the reverse. This
document keeps that direction unchanged; nothing here asks the Display to
discover or reach out to a Hub. See "Discovery and connection lifecycle,"
below, for why this is the pragmatic choice and not merely the path of least
resistance.

## Threat model

**Adversary.** Lux's cross-host case is a *single user's own multiple
machines* — a laptop, a desktop, a home server — not a multi-tenant service
with mutually distrusting principals. The realistic adversary is therefore
someone or something on the network path who is **not** that user: another
device on the same LAN or Wi-Fi, a compromised machine elsewhere on the
network, or an opportunistic scanner that finds an open port. It is
explicitly **not** a threat model against the user's own other machines —
if the user's own laptop is compromised, no transport policy protects the
Display from it, because the laptop already holds legitimate credentials.
That framing is what keeps the design proportionate: this is device-pairing
for one person's own hardware, not a service authenticating unrelated
tenants, and the mechanism should look like the former (SSH `known_hosts`,
Tailscale's own key exchange, a personal CA) rather than the latter
(a public PKI, an OAuth tenant model, a directory service).

| # | Can the adversary... | Without valid credentials | With a stolen/leaked credential |
|---|---|---|---|
| T1 | Connect and speak the Hub protocol at all | **No** — TLS handshake fails closed before any application byte is read (see "Transport specification") | Yes — the credential *is* the authorization; see "Consequences of credential loss" |
| T2 | Read another Hub's or the user's scene/menu content over the wire | No — TLS provides confidentiality; a passive eavesdropper sees ciphertext only | N/A — this axis is about eavesdropping, not impersonation |
| T3 | Inject content attributed to a real, already-connected Hub | No — cannot present that Hub's private key; cannot complete the handshake as that identity | No — a stolen credential lets the attacker impersonate the *credential's own* Hub, never a different one they don't hold |
| T4 | Cause a collision in the Display's per-`HubId` stores by claiming an already-live hostname | No — see "Resolving the trust fork," below: hostname is cert-verified, not self-reported | Only the same machine the credential was issued to; not a forgery of a different machine's identity |
| T5 | Bypass DES-086's per-connection read/write scoping once connected as a legitimate Hub | No — DES-086 is transport-agnostic; an authenticated Hub still only reads/writes its own `ConnectionId`-scoped content (see "Reconciliation") | No — same answer; credential theft grants *that Hub's own* scope, not another's |
| T6 | Downgrade the connection to an unauthenticated or unencrypted one | No — the cross-host listener never accepts `kind="test"` and never falls back to plaintext (see "Transport specification") | N/A |

**Consequences of credential loss.** A stolen private key for one enrolled
machine lets the attacker act as *that* machine's Hub — read and write
exactly the content the real Hub would have, until the credential is
revoked. This is symmetric with SSH: a stolen host key compromises that
host's identity, not the whole fleet's. Revocation is "Rejected
alternatives," below, addresses directly: this design accepts coarse,
whole-CA revocation as a proportionate trade-off for a personal, small-N
deployment, and states the cost plainly rather than hiding it.

**Out of scope, explicitly.** Denial of service (an attacker flooding the
port) is not defended against beyond what TCP/TLS already provide; a
malicious *already-enrolled* Hub process is not defended against beyond
DES-086's scoping (per T5, it never gains cross-Hub reach, but it is fully
trusted for its own scope, same as today); and physical or OS-level
compromise of an enrolled machine is out of scope for the reason stated
under "Adversary," above.
