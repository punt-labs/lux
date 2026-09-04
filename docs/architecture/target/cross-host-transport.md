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

## Transport specification

### Options considered

| Option | Confidentiality + integrity | Authentication | New moving parts | Verdict |
|---|---|---|---|---|
| **TLS 1.3, mutual auth (client + server certs)** | Built in | Built in — the same handshake that encrypts also authenticates both sides | One cert/key pair per enrolled machine; a personal CA | **Recommended** |
| Plain TCP + application-level HMAC/token | None on the wire — content is readable in transit | A shared secret can authenticate, but only after the fact (the content already crossed the wire before any check runs at the application layer) | A token-issuance and rotation story, *and* still need TLS separately for confidentiality — this option ends up needing everything TLS already provides plus its own mechanism | Rejected — see below |
| TLS with server-only cert (like ordinary HTTPS) + bearer token | Built in, one direction verified | Server authenticated to Hub; Hub authenticated to server only by the bearer token, sent *after* the encrypted channel is already open to an unverified peer... no, the server is verified, the client is not, until the token arrives | Token issuance/rotation, self-signed cert pinning (TOFU) for the server | Rejected — see below |
| SSH port-forward / SSH tunnel | Built in (SSH's own transport) | Built in (SSH's own key auth) | A dependency on the system SSH client/agent, and a tunnel process to keep alive per connection | Rejected — see below |
| Public CA (Let's Encrypt-style) | Built in | Built in | Requires public DNS + inbound internet exposure for domain validation | Rejected — wrong shape for a LAN/VPN-scoped personal tool |

**Recommendation: TLS 1.3, mutual authentication, against a small
per-user personal Certificate Authority.** One mechanism supplies both
confidentiality/integrity (T2 in the threat model) and authentication
(T1, T3, T4) from a single, well-understood, already-hardened protocol —
Lux does not implement its own cryptography anywhere in this design; it
configures `ssl.SSLContext` with `verify_mode=ssl.CERT_REQUIRED` on both
ends and `minimum_version=ssl.TLSVersion.TLSv1_3`, and everything else is
the standard library and OpenSSL's problem, not lux's. That is the
minimize-trusted-code argument in concrete form: the amount of new code
this design adds is a certificate-issuance script and a socket-listener
change, not a hand-rolled auth protocol.

**Why plain TCP + a token is rejected.** A bearer token authenticates the
holder but does nothing for the wire itself — Lux's replicated UI state is
exactly the kind of content DES-086 already treats as sensitive enough to
scope per connection (T2 in the threat model), so shipping it in the clear
across a network the moment cross-host is enabled is not proportionate,
token or no token. And once TLS is added back in for confidentiality, the
token is authenticating a channel that TLS could have authenticated
directly with a client certificate — the token becomes pure overhead, a
second mechanism doing a job the first one already does more completely.

**Why server-only TLS + bearer token is rejected.** This is the ordinary
HTTPS-with-an-API-key shape, and it is tempting because it needs no
client-side certificate machinery. It fails T3 more subtly than plain TCP
does: the token is a single shared secret, so revoking *one* compromised
machine means rotating the token *everywhere*, and there is no way to tell
which enrolled machine actually sent the request — `HubId.hostname` would
have nothing cryptographic to derive from (this reopens exactly the trust
fork "Resolving the trust fork" just closed, pushing back toward option
(b)'s cosmetic-hostname shape for no good reason). Mutual TLS gives every
enrolled machine its own credential and its own verifiable name for free;
a shared token gives neither.

**Why SSH tunneling is rejected.** It solves the same problem and solves
it well, but it makes the transport depend on an external program (the
`ssh` client, an agent, a `known_hosts` file) that lux does not control and
would need to spawn, supervise, and reconnect as a subprocess — trading a
library-level TLS configuration for a process-management problem. If a
future operator wants to run Lux over an SSH tunnel or a VPN mesh (Tailscale,
WireGuard) instead of this document's mTLS, nothing here prevents it — the
Hub-to-Display wire protocol underneath is transport-agnostic exactly the
way addressing.md's identity model is, per "Coexistence with the local
fast path," below — but lux does not build that integration itself.

### Coexistence with the local fast path

The `AF_UNIX` leg is unchanged and stays the default. A same-host Hub keeps
connecting to `DisplayPaths.socket_path` exactly as it does today —
`0700`, no TLS, no certificate, the identical trust argument addressing.md
already documents. Cross-host is **additive and opt-in**: the Display gains
a *second* listening socket, bound only when the operator explicitly
enables it (mirroring `LoopbackTransportPolicy`'s fail-closed default — no
network listener exists until asked for, and the default bind, if
unconfigured, remains loopback-only so "enabled but misconfigured" degrades
to "still local," never to "silently reachable from the network").

Both legs feed the *same* `SocketListener` machinery. `ssl.SSLSocket` is a
subtype of `socket.socket` — `select.select`, `.recv`, and `.send` behave
identically to a plain `AF_UNIX` socket once the TLS handshake has
completed — so `poll_clients`, `_read_from_client`, `remove_client`, and
every fd-keyed dict in `socket_server.py` need no change at all. The one
change is in `accept_connections`: it must poll a second listening socket
(bound `AF_INET`/`AF_INET6`, wrapped with the server's `ssl.SSLContext`),
and it must not hand a freshly-accepted TLS connection to the ordinary
accept path until the handshake — including client-certificate
verification — has fully completed. This is the one place a naive
implementation could reopen "authenticate before content": if a
non-blocking accept adds the raw, unhandshaked socket to `_clients`
immediately (as today's `accept_connections` does for `AF_UNIX`, where
there is no handshake to wait for), a `SceneMessage` could in principle
race the handshake. The specialist mission implementing this must drive
the TLS handshake to completion (blocking is acceptable here — it is a
one-time per-connection cost, not a per-frame one) before the fd ever
enters `_clients`/`_readers`.

The wire protocol itself — message framing, `ConnectMessage`,
`SceneMessage`, everything in `protocol/` — does not change. This is the
architectural payoff of treating TLS as a socket-layer concern: the
Hub-to-Display application protocol addressing.md builds on is identical
on both legs, and a Hub process's own code (`DisplayLink.connect`) differs
only in which socket family and `ssl` wrapping it uses to reach the
Display, not in what it sends once connected.

## Discovery and connection lifecycle

### Endpoint discovery — pragmatic, no registry

The Hub is the connecting party, and the operator's own instruction is not
to over-engineer discovery. There is no Hub registry, no broadcast, no
service-discovery protocol (mDNS/DNS-SD), and no rendezvous server. A
remote Hub's machine holds a small, per-user config file naming the
Display's `host:port` and the fingerprint of the CA it should trust — the
network equivalent of `DisplayPaths.socket_path` being "one well-known
filesystem location per user." Populating that file is part of enrollment
(see "Authentication and enrollment," below), a one-time, explicit,
user-driven step, not a live discovery protocol.

**What this deliberately does not solve.** If the Display's reachable
address changes (a laptop's DHCP lease renews, a home server's public IP
rotates), the remote Hub's config goes stale until the user updates it, or
until it is superseded by whatever stable-addressing mechanism the user
already relies on for that network (a static LAN reservation, a VPN mesh
with its own stable hostnames such as Tailscale, a dynamic-DNS record).
Lux does not attempt to solve address stability itself — that would be
exactly the "heavy registry" the operator ruled out, and the tools that
already solve it well are outside Lux's scope to reinvent.

### Who initiates, and why that direction is kept

The Hub dials the Display in both the same-host and cross-host cases. This
is not a new choice — it is the same direction the `AF_UNIX` leg already
uses — and cross-host keeps it for two reasons. First, symmetry:
preserving the existing direction means the Display keeps being the
listener/server side it already is, and a Hub's connect path
(`DisplayLink.connect`) changes only in socket family and TLS wrapping, not
in which end initiates. Second, and more directly a security argument: if
the Display initiated connections *to* Hubs instead, it would need to
discover Hub endpoints itself — which reintroduces the registry the
operator ruled out — and it would need Hub-side listeners bound and
reachable, multiplying the number of network-facing accept loops in the
system from one (the Display's) to one per Hub. Keeping the Display as the
sole listener keeps the network attack surface to exactly one opt-in,
authenticated port, everywhere.

### Connect, cross-host

1. The Hub opens a TCP connection to the Display's configured `host:port`.
2. Both sides perform the TLS 1.3 handshake with mutual certificate
   verification (`CERT_REQUIRED` on both ends). A connection whose peer
   cannot present a certificate signed by the trusted CA is rejected at
   this step — no application byte is ever read from it (T1 in the threat
   model).
3. Once the handshake completes, the Display sends `ReadyMessage` — the
   identical first frame the `AF_UNIX` leg sends today, unchanged.
4. The Hub responds with `ConnectMessage(kind="hub", hub_id=...)`, the
   identical second frame the `AF_UNIX` leg sends today, unchanged.
5. The Display extracts the verified hostname from the peer certificate's
   SAN, compares it against the `hostname` half of the self-reported
   `hub_id`, and rejects (closes the connection, logs server-side) on any
   mismatch — see "Resolving the trust fork," above. On a match, `HubId` is
   now verified and enters `AddressBook`'s live set exactly as the
   same-host case does.
6. From this point forward, everything in addressing.md's model — per-Hub
   store keying, ambiguity computation, title elision — applies
   identically to this connection and to a same-host one. This document's
   job ends here; addressing.md's begins.

**A cross-host connection never declares `kind="test"`.** The test-kind
backdoor (`DisplayLink`'s own docstring: "a deliberately wrong-looking
name... the display logs and rejects a `SceneMessage` sent under it")
exists for local development, and its safety today rests on the same
`0700`-socket trust the rest of the `AF_UNIX` leg relies on. The cross-host
listener refuses `kind="test"` outright — closing the connection rather
than accepting a read-only backdoor whose entire safety argument does not
carry across a network (T6 in the threat model).

### Reconnect

A dropped TCP connection (network blip, the Hub process itself restarting)
reconnects through the identical five-step sequence above — a fresh TLS
handshake, a fresh `ConnectMessage`. Whether the resulting `HubId` is
treated as "the same Hub reconnecting" (addressing.md's requirement 3) or
"a new, distinct Hub" depends entirely on whether `HubId`'s two fields
compare equal to the prior connection's, which is `addressing.md`'s own
type-level question, not this document's:

- **`hostname`** is stable across any reconnect, including a full process
  restart, because the enrolled certificate (see "Authentication and
  enrollment") lives on disk on the Hub's machine and does not change
  between runs. This document's contribution to requirement 3 is exactly
  this: the transport-verified half of `HubId` survives everything short of
  re-enrollment.
- **`pid`** does not survive a genuine OS process restart — a crash-respawn
  gets a new pid, like any other process. This is not a defect this
  document introduces; it is a property of `HubId`'s own field choice in
  addressing.md, which this document neither can nor should paper over.
  Flagged here as a coordination point: a Hub process that restarts (not
  merely reconnects its socket after a network blip) will present a
  `HubId` differing only in `pid`, which addressing.md's own
  same-host-duplicate path already handles correctly (`pembroke`,
  `pembroke (2)`, re-eliding once the stale entry is reaped) — the
  behavior is *correct*, just worth naming explicitly so nobody reads
  requirement 3's "(network blip, restart)" parenthetical as a promise
  this document cannot make for the `pid` field.

### Preemption — a coordination point, not resolved here

`SocketListener.hub_fd_for(name)` and `HubReconciliation._preempt_stale_hub`
key single-owner preemption on the connection's declared `name`
(`ConnectMessage.name`), not on `HubId`. addressing.md keeps `name`'s
meaning as "what a human calls this connection" and states explicitly that
`hub_id` is the separate, dedicated identity field — it does not say `name`
becomes a real per-process value. Read literally, that means preemption
today (and after addressing.md's own changes land) still keys on whatever
string populates `name`, which several Hub processes may legitimately
share (`_DISPLAY_CLIENT_NAME`, the existing hardcoded constant). For a
single same-host Hub this is harmless — there was only ever one Hub to
preempt. Once cross-host makes two independently-legitimate, simultaneously
live Hubs possible, name-keyed preemption risks a reconnecting Hub on one
machine evicting a live, unrelated Hub on a different machine that happens
to share the same declared `name`.

This document does not resolve it, because the fix touches `name`'s own
semantics, which is addressing.md's territory, not this document's transport
boundary. It is recorded here as an explicit **coordination point** for
implementation: whichever bead reworks preemption should key it on `HubId`
(the value this document guarantees is both verified and, per
"Reconnect" above, hostname-stable) rather than `name`, and that choice
should be made once, consistently, referenced from both documents rather
than decided twice.

### Disconnect

No new mechanism. A dropped cross-host connection is, from `SocketListener`
and `HubReconciliation`'s point of view, an ordinary fd closing — the
existing per-fd scene reaping, `AddressBook` live-set removal, and lease
sweep apply exactly as addressing.md already specifies for the same-host
case (its "Disconnect needs no new logic" point). Nothing about the TLS
layer needs its own teardown path beyond closing the underlying socket,
which tears down the TLS session with it.

## Authentication and enrollment

### The trust root is the user, not a service

Per the threat model, the person enrolling a second machine already has
authenticated access to both machines — they are not proving their identity
to Lux, they are telling Lux "these two machines are both mine." Enrollment
is therefore a manual, explicit, out-of-band act, not a live network
protocol Lux implements and must then defend on its own. This mirrors SSH's
own `known_hosts` model more than a corporate PKI's.

### Mechanism

1. **CA creation (once, on the Display's machine).** The first time cross-host
   is enabled, the Display generates a small personal Certificate Authority
   — a private key and self-signed root certificate — stored under
   `~/.punt-labs/lux/ca/` with the same discipline the socket directory
   already uses (`0700` directory, `0600` private key). This CA signs only
   Lux's own leaf certificates; it is not a general-purpose trust root and
   is never installed into the OS or browser trust store.
2. **The Display's own leaf certificate.** The Display issues itself a leaf
   certificate (SAN = the hostname it will present as) signed by that CA,
   for the server side of the mTLS handshake.
3. **Per-machine enrollment (once per additional Hub machine).** On the
   machine that will run a Hub, the operator generates a local keypair and
   a certificate signing request naming that machine's own hostname as the
   SAN. The CSR is signed by the Display's CA — **the CA's private key
   never leaves the Display's machine.** The signing step itself is a
   manual, offline exchange: the operator copies the CSR to the Display
   (however they already move files between their own machines — `scp`, a
   USB drive, a password manager's file attachment) and copies the signed
   certificate back. This is the "no heavy registry" instruction taken
   literally: enrollment needs no running service, no listening enrollment
   port, and no protocol beyond the operator's own file-transfer of choice.
4. **Result.** Each enrolled machine holds its own private key and a
   certificate binding it to its own hostname, signed by one shared CA both
   sides already trust. This is exactly the material "Resolving the trust
   fork" needs: the certificate's SAN *is* the verified hostname the
   transport hands to `HubId`.

**A convenience path is deliberately not specified here.** A future,
friendlier enrollment flow — a short-lived pairing code exchanged over the
LAN during the bootstrap step, closer to Tailscale's `authkey` or
Syncthing's device-ID pairing — is a real usability improvement over
copy/paste CSR signing, but it is its own protocol with its own threat
model (a pairing code is a bearer credential with a race between
generation and use) and deserves its own design pass rather than being
folded into this one under time pressure. The manual CSR-signing path above
is deliberately the whole of what this document commits to; a convenience
layer on top is noted as a rejected-for-now alternative below, not a gap.

### Rejected alternatives

**Distribute the CA's private key to every machine.** Simpler than CSR
signing — each Hub machine could mint its own leaf certificate locally
without a round trip to the Display. Rejected because it multiplies the
number of places the single most sensitive secret in this design lives:
every enrolled machine becomes capable of impersonating *any* Hub, not just
itself, which fails T3 and T4 more broadly than a leaked leaf key does. The
CSR-signing flow costs one extra manual round trip at enrollment time in
exchange for keeping the CA key on exactly one machine.

**A pre-shared/derived token instead of mTLS.** Addressed in "Transport
specification," above — rejected there because it needs TLS added back for
confidentiality regardless, at which point mutual TLS supplies both
properties from one mechanism rather than two, and because a shared token
cannot give `HubId.hostname` anything cryptographic to anchor to without
falling back to option (b) of the trust fork this document just closed.

**Leveraging the org's ethos/GPG identity infrastructure.** Considered
directly, because the org already has a working per-identity ed25519 GPG
key story (`CLAUDE.md`'s own Claude Agento identity, `C48E101AB522FB17`).
Rejected for a mismatch of what is being identified: ethos identities are
bound to a *person or agent* (a human, or an agent acting on a repo), while
`HubId` needs to identify a *machine* — the same person's two laptops need
two distinct, independently-revocable identities, not one shared identity
authenticating both. Reusing ethos's GPG keys here would either issue one
key per machine anyway (in which case it is a parallel, second PKI doing
the same job this document's CA already does, with none of the tooling
built for it) or authenticate by *person* and leave machine disambiguation
to the self-reported `hostname` field again — precisely the unverified-field
problem "Resolving the trust fork" closes. GPG-signed challenge/response is
also simply a different cryptographic mechanism for proving key possession
than TLS's own handshake already is, without adding a property TLS lacks.
The org's ethos infrastructure remains the right tool for what it already
does — signing commits, authenticating agents to `git`/`gh` — and this
document does not ask it to do a second, structurally different job.

**Revocation via a live CRL/OCSP responder.** A textbook PKI would run a
certificate-revocation service so a stolen leaf key can be invalidated
without touching every other certificate. Rejected for this deployment's
scale: running a CRL/OCSP responder is exactly the "heavy" infrastructure
the operator ruled against, for a threat this document already scopes to a
handful of machines one person owns. The accepted trade-off instead:
revoking one compromised machine means regenerating the CA and
re-enrolling every machine, an explicit, bounded, rare, fully manual
operator action — not a hidden footgun, because nothing silently trusts a
revoked key in the meantime; the operator's own next action (regenerate,
re-enroll) is what closes the window, same as rotating a leaked SSH host
key today.
