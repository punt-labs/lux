# Client Calls: Test-Partition Coverage Audit

Companion to `docs/client_calls.tex` and `docs/client_calls_locks.tex`, the
models of the Hub's typed request to a provider client (DES-107 in
`DESIGN.md`). Verify with `scripts/verify_client_calls_model.sh` (it is part of
`make check-models`).

The implementation (DES-107 work units 3 to 5) is not written yet. This note
therefore records two things: the mapping from spec operations to the design
elements that will realise them, and the test each partition obliges the
implementation to carry. Every row below is an obligation until the test exists.
Fill the "Covering test" column as each unit lands; a partition with no test is
a gap, not coverage.

## Spec operation to design element

| Spec operation | Design element (DES-107) |
|---|---|
| `OpenConn` | a listen leg completes its handshake (`ClientRegistry`) |
| `RegisterSvc` | `service register`, a store-locked `ClientLifecycle` step, gated by `push_required` |
| `RegisterRefused` | `service register` by a different connection: `rejected` |
| `Dispatch` | `ClientCalls`: with the registry lock held, find the provider's session, mint the id, enter the call as pending, start its deadline, queue the `RequestFrame` with `call_soon_threadsafe` |
| `Serve` | `LuxHubClient.on_request` running the handler as its own task |
| `ReplyFrame` | the listen reader matching a `ReplyFrame` by `(request_id, session)` |
| `RefuseFrame` | the listen reader matching a `RefusalFrame` by `(request_id, session)` |
| `Timeout` | the 15 s deadline on the waiter's event |
| `SessionEnd` | the `ClientLifecycle` step for disconnect, lease lapse and teardown: withdraws registrations, drops queued frames, resolves pending calls `lost` |
| `Supersede` | a newer listen leg of the same client: `SessionEnd` of the old session and the new session's start, one step |

## Invariant partitions

The model proves each over every reachable state of a carrier of two
sessions, two requests and two keys, with a per-provider limit of 1. The test is
the code-level check of the same statement.

| Partition | Statement | Fails in variant | Test the implementation must carry |
|---|---|---|---|
| C1 | a call leaves pending once; the waiter sees one outcome | none (guarded) | reply and timeout racing on one call: the waiter gets exactly one outcome |
| C2 | a reply or refusal counts only from the session the request went to | `reply_any_session_buggy` | a second connection sends a `ReplyFrame` naming a pending id: dropped, logged, the call stays pending |
| C3 | an outcome removes the entry; a later frame is dropped | none (guarded) | a reply after a timeout is dropped and does not satisfy a later call |
| C4a | no pending call outlives its session | `session_end_keeps_pending_buggy`, `dispatch_split_buggy` | disconnect, lease lapse and supersession each resolve every pending call before the lifecycle step returns; a call made while the provider's session ends is either entered before the end (and resolved by it) or refused, never left pending on the dead session |
| C4b | nothing is redelivered to a successor | `replay_on_reconnect_buggy` | after a reconnect the successor receives no `RequestFrame` for a call made before it |
| C4c | a call resolved by a session end or supersession has outcome `lost`, and `lost` arises only that way | `session_end_wrong_outcome_buggy` | each of disconnect, lease lapse and supersession gives the waiter `provider_lost`, never `timeout`; a timeout never reports `provider_lost` |
| C5 | every pending call has its own deadline started | `no_deadline_buggy` | each call entered in the table has its own 15 s deadline, whatever else is pending (two calls pending: both time out; fake clock) |
| C6 | no lock is held while waiting; the wake follows the table lock's release | `locks_wait_held_buggy`, `locks_wake_held_buggy` | a pending call does not block `service register` or a session end on another thread |
| R1 | a registration is held by a live session | none (guarded) | session end withdraws its registrations in the same step |
| P1 | at most `maxPend` pending per provider (8 in the code, 1 in the model) | `no_cap_buggy` | the ninth call is refused `rejected`, "provider busy", and never sent |
| Lock order | store, then registry, then table; deadlock-free at two and three threads | `locks_inverted_buggy` | an acquisition-order guard in tests of `ClientCalls` and `ClientLifecycle` |
| Lookup and entry | a call holds the registry lock across finding the provider and entering the table | `dispatch_split_buggy` | a session end racing a call: the call never ends pending on the ended session |

## Reachability (the checks are not vacuous)

The script also shows these reachable in the intact model: a pending call, each
of the four outcomes, a provider at its limit, a refused registration and a
supersession.

## What the model abstracts

- The deadline is a started timer, not a clock. C5 is a per-call state
  invariant: each pending call has its timer started, which enables its own
  `Timeout`. The timer may fire at any later point.
- The limit of 8 is scaled to 1 so a carrier of two requests exceeds it.
- A refusal at the front door (no provider, provider busy, caller not
  identified) changes no state and is not an operation. A frame that fails
  the match is dropped and changes nothing; it is not an operation either.
- The environment may send a reply from any live session. The model does not
  say that the honest provider replies only after serving.
- The provider's own daemon exchange, the 256-token memory and the payload cap
  are outside the model: they are below the relay.
- The lock model's wake-up is per thread: a signal or a deadline sets one
  caller's event, and a wait consumes only its own.
