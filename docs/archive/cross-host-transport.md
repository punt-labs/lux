# Lux Cross-Host Transport and Trust

> **Archived 2026-09-04 — superseded; retained for history.**
> This was the evaluator-accepted design draft for DES-090. Per operator
> direction (2026-09-04), its architecture content was restructured into
> `docs/architecture/system.tex` §"Cross-Host Transport and Trust," and
> its implementation plan into
> `docs/architecture/multi-hub-addressing-work.md`. DES-090 in
> `DESIGN.md` remains Status: PROPOSED, pending operator ratification,
> and now points at those two documents instead of this one. This draft
> is kept for the reasoning trail only — do not use it to guide
> implementation. See `docs/archive/README.md` for why this was
> archived.

**Status:** canonical target for the cross-host Hub-to-Display transport
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
host's identity, not the whole fleet's. Revocation itself is addressed
directly in "Rejected alternatives," below: this design accepts coarse,
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

**Session resumption.** `ssl.SSLContext` enables TLS session tickets by
default on both the client and server sides, and this design does not
disable them. That is deliberately left as-is rather than hardened
away: under TLS 1.3, session resumption is not a new, unauthenticated
handshake — the resumption ticket is cryptographically bound to the
original full handshake, including the mutual certificate exchange
this document requires, so a resumed connection still carries the
*same* verified identity the original handshake established, not a
fresh or weaker claim. Python's `ssl` module also exposes no public
API for TLS 1.3 0-RTT/early data — the one property of session
resumption with a well-known replay weakness — so that risk does not
arise here at all. Nothing in "Resolving the trust fork," above, or
its SAN/`hub_id` cross-check needs to re-run per resumed connection:
the identity a resumption ticket carries is exactly the identity the
handshake it resumed already proved.

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
race the handshake.

**The handshake itself must never block the render thread.**
`accept_connections` and `poll_clients` both already run synchronously
inline on the single render thread, once per frame (`render_loop.py`'s
`_on_frame`) — the reason `SocketListener` already carries
`_frame_deadline`, `set_frame_deadline`, and `_ONE_OFF_SEND_BUDGET`,
bounding every other network wait this module performs on that thread.
A blocking `do_handshake()` call has no such bound: a peer that
completes the TCP handshake and then stalls or trickles its
`ClientHello` would hang that one call for as long as it likes,
freezing rendering *and* the same-host `AF_UNIX` leg for every Hub,
with no credential required — exactly T1's "opportunistic scanner,"
and exactly the render-loop-freezing denial of service this document's
own threat model exists to rule out. Fail closed, not hung.

The specialist mission implementing this must instead drive the TLS
handshake the same way `SocketListener` already drives every other
bounded, per-frame network operation: **non-blocking, pumped through
the existing accept/poll cadence, under a bounded per-connection
deadline**, mirroring `set_frame_deadline`'s own monotonic-timestamp
pattern rather than inventing a new one:

1. Wrap each newly-accepted `AF_INET`/`AF_INET6` socket in the server
   `ssl.SSLContext` with `do_handshake_on_connect=False`, set it
   non-blocking, and hold it in a new *pending-handshake* set keyed by
   fd — kept separate from `_clients`/`_readers`, so no fd reaches
   either dict, and therefore no message is ever read from it, before
   its handshake is verified complete. Record a deadline
   (`time.monotonic() + _HANDSHAKE_BUDGET`, a small constant on the
   order of a few seconds: generous for a legitimate peer's round
   trip, tight enough that an attacker cannot hold the socket open
   indefinitely) alongside the pending entry.
2. Each frame, `accept_connections` calls `do_handshake()` once per
   pending connection. `ssl.SSLWantReadError`/`ssl.SSLWantWriteError`
   are the expected non-blocking retry signals — on either, leave the
   connection pending and retry next frame; any other `ssl.SSLError`
   (untrusted CA, bad cert, protocol failure) closes the socket and
   drops it immediately, the same as a hard reject.
3. A pending connection whose deadline has passed is closed and
   dropped unconditionally, mid-handshake if need be. This is the
   fail-closed backstop: a stalled or slow-rolled handshake costs the
   Display at most one bounded, per-connection budget of wall-clock
   time, never an unbounded block.
4. Only once `do_handshake()` returns successfully does the connection
   move from the pending set into `_clients`/`_readers` — and only
   after the SAN/`hub_id` cross-check in "Resolving the trust fork"
   also passes, once `ConnectMessage` arrives.

This keeps the entire cross-host listener on the same single render
thread as everything else in `socket_server.py` — no new thread, no
lock, no cross-thread handoff of `_clients` or any other
render-thread-owned state, which is not a `SocketListener`
responsibility today and stays that way. A bounded background thread
performing accept+handshake off-thread and enqueueing only the
completed, verified socket was considered as the alternative and is
rejected here: it would be the first thread ever introduced into
`SocketListener`'s otherwise single-threaded, lock-free design, and
the queue handoff becomes a second interleaving surface needing its
own correctness argument — for a problem the module's existing
per-frame-budget pattern already solves without one. Minimizing new
concurrent machinery is the security argument here, not merely a
style preference: fewer interleavings is less attack surface to
reason about, model, and get wrong.

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
   is never installed into the OS or browser trust store. The private key
   should additionally be passphrase-protected at rest, and
   `~/.punt-labs/lux/ca/` kept out of any dotfile-sync or cloud-backup tool
   the operator runs elsewhere on that machine — this exact user population
   runs that kind of tooling, and syncing this design's single most
   sensitive secret to a second location defeats the "the CA's private key
   never leaves the Display's machine" guarantee "Rejected alternatives,"
   below, relies on.
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

### Certificate lifetime, expiry, and rotation

**Validity periods.** The CA's self-signed root certificate is issued
with a long validity (10 years) — it is regenerated only on a full
re-enrollment event ("Rejected alternatives," below), not on a
schedule, so a short CA lifetime would just force premature,
unmotivated re-enrollment of every machine. Each leaf certificate (the
Display's own and every enrolled Hub's) is issued with a much shorter
validity (1 year), matching the general TLS-ecosystem posture that a
short-lived leaf bounds the damage window of a leaked leaf key without
adding the operational cost of a leaked CA key — one leaf expiring
touches one machine; the CA does not need to be short-lived to get
that benefit, because it is never the credential presented on the wire
(only leaves are).

**The operator-facing failure mode today: silent and indistinguishable
from network failure.** An expired leaf fails the TLS handshake with a
certificate-verification error (`ssl.SSLCertVerificationError`,
`certificate has expired`) on both sides — this is correct,
fail-closed behavior per "Invariants," below, and no different in kind
from any other handshake rejection. What is *not* yet solved is
diagnosis: `DisplayLink`'s reconnect loop treats every connection
failure alike, so an expired leaf looks identical to "Display
unreachable," "network partition," or "wrong endpoint configured" —
the Hub retries forever, and the operator has no signal pointing at
"your certificate expired, re-enroll" specifically. This document
requires that the implementation close that diagnosability gap, not
the security gap (there is none — expiry already fails closed): the
Display's server-side log must record the specific rejection reason
(never surfaced to an unauthenticated peer, per the error-message
discipline threat modeling already implies — revealing "expired" versus
"wrong CA" versus "bad SAN" to an unauthenticated network peer would
be an oracle), and the Hub-side `DisplayLink` client, which *does* hold
a legitimate identity and is not an adversary, should surface a
distinct, actionable message ("certificate expired — re-enroll this
machine") rather than a generic connection-failure retry loop.

**The explicit trade-off, stated rather than left silent.** Exactly as
"Rejected alternatives" states plainly for CRL/OCSP below: there is no
automatic renewal in this design. A leaf's expiry is a fully manual
event — the operator re-runs the same CSR-signing enrollment flow
described in "Mechanism," above, for the one affected machine. For a
handful of personally-owned machines, a yearly manual touch per
machine is a proportionate cost; an automatic-renewal protocol would be
new standing machinery (a renewal endpoint, a renewal credential, a
second thing that can be attacked) to save an operation this document
already keeps deliberately rare and manual for every other lifecycle
event (initial enrollment, revocation). The cost is bounded and
foreseeable, not a hidden footgun: an expiring leaf gives ample advance
warning in practice (the certificate's own `notAfter` field), and nothing
about this document prevents an operator from checking it proactively
before the reconnect loop ever has to discover it the hard way.

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

## Invariants

Stated precisely, so the implementation and its tests have a checkable
target rather than prose to interpret:

1. **No content before verification.** No `SceneMessage`,
   `CallbackMenuMessage`, `HubManifestMessage`, or any other content-bearing
   frame is processed from a connection until that connection's `HubId` has
   been both transport-verified (TLS handshake with client-cert
   verification complete) and cross-checked (self-reported `hub_id`
   hostname matches the certificate SAN). This is addressing.md's
   requirement 1, restated as a transport-side obligation.
2. **At most one live connection per `HubId`.** Once preemption is
   re-keyed onto `HubId` (see "Preemption — a coordination point," above),
   a second connection presenting the identical verified `HubId` evicts the
   first, never coexists with it — the same single-owner guarantee DES-068
   already established for the (today, single) same-host Hub, generalized
   to N verified Hubs.
3. **Hostname verification is fail-closed.** A SAN/`hub_id` mismatch, an
   untrusted or expired certificate, or a `kind="test"` declaration on the
   cross-host listener all result in connection rejection, never a
   degraded-trust fallback (no "accept but flag," no "accept and log a
   warning"). Fail closed, not open.
4. **The `AF_UNIX` leg's trust argument is untouched.** Nothing in this
   design weakens, bypasses, or shares state with the local socket's
   `0700`-permission trust boundary; a same-host Hub's connection carries
   exactly the same guarantees after this document ships as before it.

### z-spec assessment

**Two of the invariants above are z-spec-REQUIRED for the implementation
phase.** This document does not model them now — per the mission's
instruction, flagging is the deliverable here, not the model — but the
reasoning for *why* they clear WORKFLOW.md's z-spec trigger list is stated
precisely so the implementation mission cannot reasonably skip it:

- **Invariant 1 (no content before verification) is a stateful-protocol
  safety property with a real interleaving.** The connection's own state —
  "TCP connected," "TLS handshaking," "TLS verified, awaiting
  `ConnectMessage`," "identified, `HubId` verified," "receiving content" —
  is exactly the shape WORKFLOW.md names as a z-spec trigger ("a defined
  set of states and transitions" with a safety invariant of the form
  "never X while Y"). The concrete race a model-check should exhibit and
  then exclude: a non-blocking accept path that adds a socket to
  `_clients`/`_readers` before its TLS handshake — or before its
  `ConnectMessage` — has actually completed, letting a `SceneMessage`
  arrive and be processed against an unverified or not-yet-identified
  connection. "Coexistence with the local fast path," above, already names
  this as the one place a naive implementation could reopen the gap; a
  z-spec model is what proves the chosen implementation closes it
  exhaustively rather than merely "in the cases tested."
- **Invariant 2 (at most one live connection per `HubId`) is a lock/ownership
  discipline across a reconnect race, with multiple remote Hubs
  interleaving.** This is the same shape DES-068's own single-owner
  preemption already needed a careful sequential argument for (see
  `_preempt_stale_hub`'s docstring: "closing the interleaving where a
  straggling message from a superseded connection could re-materialize a
  scene a fresh manifest just purged") — generalizing it from one Hub to N
  concurrently-reconnecting Hubs is precisely the class of change
  WORKFLOW.md's recurrence signal calls out: "the MOMENT the same class of
  defect surfaces across two or more fix/review rounds — stop... formalize
  the state machine." A reconnect racing its own predecessor's teardown,
  under network jitter, with more than one remote Hub doing it
  simultaneously, is exactly the kind of interleaving that testing samples
  and model-checking proves exhaustively.

**Not z-spec candidates:** invariants 3 and 4 above are boundary checks and
a non-interference statement, not concurrency properties — the same
distinction addressing.md's own governing invariant draws for its
Rung-3 keying discipline ("a naming/keying convention, not a concurrency
property"). A rejection-path unit test (bad SAN, expired cert, `kind="test"`
over the network leg) and a code-level audit that no cross-host code path
touches `AF_UNIX`'s socket, permissions, or state are the right-sized
verification for those two.

**Fidelity requirement, stated in advance per WORKFLOW.md's own rule:** the
eventual z-spec model for invariant 1 must reproduce the defect when the
handshake-before-accept ordering is removed (the model exhibits a state
where content is processed against an unverified connection), and the
model for invariant 2 must reproduce a double-owner state when preemption
is re-keyed incorrectly (e.g., kept on `name` per the coordination point
above, with two same-named-but-different-`HubId` connections both live). A
model that cannot reproduce the bug it guards against is too abstract to
trust — this document states that requirement now so the implementation
mission does not have to rediscover it.

## Reconciliation with existing design

**DES-086 (scene inspection is a per-connection security boundary).**
Preserved verbatim, not weakened. DES-086's invariant operates on Rung 2
(`ConnectionId`) — a connection reads and writes only content composed on
its own `ConnectionId`, with no admin/superuser surface anywhere ("Absence
of any admin-tier operation on any surface other than the CLI is itself a
security invariant," `client-surface-parity-design.md`). This document
operates one layer below that — it decides whether a connection is allowed
to exist and speak at all, and what `HubId` it is bound to once it does. An
authenticated, verified remote Hub gains exactly the same DES-086 scoping a
same-host Hub already has: it can read and write its own `ConnectionId`-scoped
content, and nothing belonging to a different connection, whether that
connection is local or on another verified machine. Cross-host adds a gate
in front of DES-086's boundary; it does not move, widen, or bypass the
boundary itself (T5 in the threat model states this as a concrete
non-goal for an attacker, but it is equally true for a legitimate remote
Hub — mTLS authentication is not privilege escalation).

**addressing.md (DES-089).** This document satisfies, point for point, the
five requirements addressing.md's "Dependencies on the cross-host transport
layer" states: (1) authenticate before content — "Invariants," above, and
the five-step connect sequence; (2) the addressing layer performs no
authentication of its own and trusts `HubId` once delivered — nothing in
this document asks `AddressBook` or any per-store keying to re-verify
anything, verification is entirely this document's job, ending at the point
`HubId` is handed off; (3) `HubId` stability across reconnects — "Reconnect,"
above, with the `hostname`-stable/`pid`-unstable distinction stated
precisely rather than glossed over; (4) the transport owns endpoint
resolution and connection initiation — "Discovery and connection
lifecycle," above; (5) `hub_id` frame ordering — step 4 of "Connect,
cross-host," unchanged from the same-host wire sequence. The one place this
document does not resolve a question addressing.md's own text raises —
preemption's `name`-versus-`HubId` keying — is named explicitly as a
coordination point rather than silently assumed away in either direction.

**A finding against the current same-host code, surfaced because
cross-host depends on it.** `render_loop.py:757`'s
`_handle_scene`/`hub_reconciliation.py:125-141`'s
`reject_scene_if_test_kind` rejects a `SceneMessage` only when the sending
fd has already declared `kind="test"`. An fd that has **not yet sent any
`ConnectMessage` at all** — `kind_of(fd)` returns `None`, which is `!=
"test"` — is not rejected today; its `SceneMessage` is processed and
installed. This is harmless on the `AF_UNIX` leg only because the socket's
`0700` permission already means an unidentified fd is still a same-user
process, so there is no content-authenticity question to ask. It is not
harmless once a store is keyed by `HubId` (addressing.md's own bead 2):
there is no `HubId` to key an unidentified connection's content under at
all, and a cross-host connection's TLS handshake having succeeded says
nothing yet about whether `ConnectMessage` — the frame that actually
carries `hub_id` — has arrived. **This document requires closing this gap
as a prerequisite for cross-host, not an optional hardening**: every
content-bearing message handler (`_handle_scene` and its equivalents for
menus and manifests) must reject a message from any fd where `kind_of(fd)
is None`, not only `kind_of(fd) == "test"`, uniformly across both
transports. Listed as a net-new bead below.

## Implementation bead map

Net-new beads this document's design requires, listed for the leader to
file — not created here, per this mission's contract. Ordered by
dependency.

1. **Close the pre-identification content gap (prerequisite, blocks
   everything below).** Reject `SceneMessage`/`CallbackMenuMessage`/
   `HubManifestMessage` from any fd where `kind_of(fd) is None`, not only
   `kind_of(fd) == "test"` — see "A finding against the current same-host
   code," above. Ships independently of cross-host and should land first;
   it is a real gap today, cross-host only raises its stakes.
2. **Personal CA + enrollment tooling.** CA creation on first
   cross-host-enable, the Display's own leaf cert, and the manual
   CSR-signing enrollment flow ("Authentication and enrollment," above) —
   likely a small `lux display enable-remote` / `lux hub enroll` CLI
   surface. No dependency on addressing.md's beads.
3. **The cross-host TLS listener.** A second, opt-in, off-loopback-capable
   listening socket in `socket_server.py`, wired through `ssl.SSLContext`
   with `CERT_REQUIRED` both directions and `TLSVersion.TLSv1_3` minimum.
   The handshake is **non-blocking and bounded** — driven through the
   existing per-frame `accept_connections` cadence via a pending-handshake
   set and a per-connection deadline, never a blocking `do_handshake()`
   call on the render thread (see the corrected "Coexistence with the
   local fast path" guidance, above). This is the one correctness-critical
   detail: a naive blocking implementation reopens a render-loop-freezing
   denial of service inside this document's own threat model (T1).
   Depends on bead 2 for certificate material to configure against.
4. **Hostname verification at `ConnectMessage` time.** The SAN-extraction
   and `hub_id`-hostname cross-check from "Resolving the trust fork,"
   above, plus the fail-closed rejection path. Depends on bead 3 (needs a
   TLS peer certificate to read) and on **addressing.md's net-new bead 1**
   (`hub_id` wire field) — this is the shared touchpoint between the two
   documents' bead maps, and the two beads should coordinate on the exact
   `ConnectMessage` shape rather than land independently.
5. **Cross-host `DisplayLink` client path.** `DisplayLink.connect`'s
   remote-endpoint variant — reading the per-user config named in
   "Endpoint discovery," dialing TCP, wrapping in TLS with the enrolled
   client certificate. Depends on bead 2 (needs enrollment material) and 3
   (needs a listener to dial).
6. **Preemption re-keyed onto `HubId`.** The coordination point named
   under "Preemption," above — resolved jointly with whichever bead
   implements addressing.md's per-Hub-keyed storage (**addressing.md's
   net-new bead 2**), since both touch the same dedup/ownership question
   from different angles. Should not land as two independent, possibly
   conflicting fixes.
7. **z-spec models for invariants 1 and 2.** Per "z-spec assessment,"
   above — the no-content-before-verification handshake race and the
   at-most-one-live-connection-per-`HubId` reconnect race, each with a
   fidelity control per WORKFLOW.md's requirement. Depends on beads 3, 4,
   and 6 existing to model against.
8. **Threat-model regression tests.** One test per threat-model row with a
   "No" answer under "Without valid credentials" (T1, T3, T4, T6): connect
   with no client cert, connect with a cert signed by a different CA,
   connect with a `hub_id` hostname that disagrees with the cert SAN,
   attempt `kind="test"` on the cross-host listener. Each must observe
   rejection, not a degraded-trust acceptance. Depends on bead 3 and 4.

**Cross-repo coordination.** Neither vox nor z-spec run a Display — both
run Hub-side connections only (`applets/README`, DES-063) — so this
document's transport work is Display-side only and does not, by itself,
require a vox/z-spec change. The shared touchpoint both documents already
name is the `hub_id` wire field itself (addressing.md's net-new bead 1),
which vox and z-spec must adopt regardless of whether either ever runs
cross-host; this document adds no independent cross-repo requirement
beyond that one.

## Related target docs

(Paths below are relative to this archived document's location,
`docs/archive/`; addressing.md moved here together with this document, so
that link is unchanged.)

- [../architecture/target/target.md](../architecture/target/target.md)
- [../architecture/target/topology.md](../architecture/target/topology.md)
  — deployment allows Hub and Display on different machines; this
  document specifies how that connection is established safely.
- [addressing.md](./addressing.md) — DES-089, the identity ladder this
  document delivers a verified `HubId` into. Read its "Dependencies on the
  cross-host transport layer" section first; this document is that
  section's answer. Also archived here.
- [../architecture/target/element-contract.md](../architecture/target/element-contract.md)
- [../architecture/target/introspection-api.md](../architecture/target/introspection-api.md)
