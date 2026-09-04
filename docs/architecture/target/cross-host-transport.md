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

## Resolving the trust fork: `HubId.hostname` is transport-verified

addressing.md flags, without resolving, whether `HubId.hostname` stays a
transport-verified network name (its option **a**) or becomes a cosmetic
label beside a new opaque uniqueness key (its option **b**). **Decision:
option (a).** `HubId` keeps exactly the two fields addressing.md specifies
— `hostname: str`, `pid: int` — no third field. Justification, as a
security call rather than a convenience call:

**The real question is not "which option is more defensive," it is "what
does 'verified' mean if the transport authenticates the connection but not
the field."** Requirement 1 of addressing.md's dependency contract is that
the transport delivers a *verified* `HubId`, not merely that it delivers
*a* `HubId` over an authenticated channel. If the transport authenticates
the TLS session (proves "this is a legitimate credential this user
enrolled") and then passes through whatever `hostname` string the Hub
happens to self-report in `ConnectMessage.hub_id` unchecked, `HubId` is not
actually verified — it is merely carried over a verified pipe. A
misconfigured or buggy Hub process (no malice required) could self-report a
`hostname` that collides with a different, legitimately distinct Hub's
already-live entry, reintroducing the exact silent-collision failure mode
DES-086 and addressing.md both exist to close, just moved past the
transport boundary instead of solved by it.

Option (a) closes that gap directly, with a mechanism, not a preference: the
transport does not trust the self-reported `hostname` half of
`ConnectMessage.hub_id` at all. It derives the verified hostname from the
mTLS peer certificate's own Subject Alternative Name (see "Authentication
and enrollment," below — the enrollment step is what binds a certificate to
a specific machine's name in the first place) and **rejects the connection
outright if the self-reported hostname does not match the certificate's
SAN.** `pid` is passed through as self-reported, unverified, exactly as
addressing.md's own docstring already treats it: "`pid` is not
network-meaningful and never needs to be... it only ever breaks a tie
*within* one already-identified host" — there is no security property lost
by trusting a same-host tie-breaker the transport has already anchored to a
verified machine identity.

This resolves cleanly against option (b)'s own stated case for itself.
Option (b) exists because "this hostname string is unique and genuine" felt
like a harder claim to verify than "this credential is unique and genuine."
Deriving the hostname from the certificate's SAN collapses that gap to
nothing — verifying the credential *is* verifying the hostname, because the
enrollment step (not a live DNS lookup, not a reverse-DNS trick) is what
attached the name to the credential in the first place. Option (b)'s cost —
a third `HubId` field, a real/cosmetic split addressing.md does not
currently carry, and a second uniqueness axis every per-`HubId` store and
every `AddressBook` title-elision computation would need to reason about —
buys nothing option (a) does not already deliver once verification is
anchored at the certificate rather than the wire field.

**Consequence for `HubId`.** None beyond what addressing.md already
specifies. `HubId.hostname` continues to mean "a real, verified network
name" exactly as its docstring states today; this document supplies the
verification mechanism cross-host was missing, cross-checked against the
same-host case's own trust argument (the `0700` socket directory already
prevents a hostile process from lying about its identity by preventing it
from connecting at all) so the two cases are verified by different
mechanisms but make the identical claim. **Consequence for the wire
protocol.** None. `ConnectMessage.hub_id` still carries the full
`HubId.wire_token` (`{hostname}\x1f{pid}`) exactly as addressing.md
specifies; cross-host adds a rejection rule at the transport boundary, not
a new field.
