# Retry-Token Memory: Test-Partition Coverage Audit

Companion to `docs/new_tokens.tex`, the model of the token memory in DES-107
(`DESIGN.md`, decision 4). It derives the test partitions from the Z operation
schemas, as `docs/frame_expiry_coverage.md` does for frame expiry.

The code does not exist yet. Work unit 4 of DES-107 adds the `new` request's
`token` and the daemon's 256-entry memory in `luxd-pty`. The "Covering test"
column is therefore the test that work unit must write, named by the partition
it covers; none exists today, and the audit is complete only when every row has
a passing test.

The model scales 256 entries to `cap = 2` and uses three tokens and two labels.
Each launch is one atomic step because the daemon serialises launches. A test
sets the cap to a small value (a constructor argument of the memory class, not
a module constant) so it needs three launches, not 257.

## Spec operation to design element

| Spec operation | Design element |
|---|---|
| `RepeatBound` | a repeated token whose entry holds a session: reply with the original session, running or exited |
| `RepeatUnrecorded` | a repeated token whose entry has no session: `rejected`, naming the token and the logged process id |
| `RefuseLabel` | the label-taken refusal, before the entry is added |
| `RefuseConfig` | any other refusal before the fork (`allow_runtime_launchers = false`, unknown launcher) |
| `LaunchOk` | entry added, process forked, session recorded and bound to the entry |
| `LaunchForkFails` | the fork fails: the entry is removed and the oldest entry its addition dropped is restored, then `fault` |
| `LaunchUnrecorded` | the process forks, session setup fails; the entry stays unbound and the daemon logged token and pid at the fork |
| `ExitLabelled` | a recorded session exits: label freed, entry kept |
| `ExitStray` | a forked process with no session exits |
| `ExitSurvivor` | a shell that survived an earlier restart exits |
| `RestartClean` | daemon restart: memory cleared, every shell that is not itself a survivor of an earlier restart ended |
| `RestartSurvivor` | restart where a shell survives SIGKILL: token and pid logged, failure exit status, no history for the survivor |

## Invariants

| Id | Statement | Model check |
|---|---|---|
| T1 | a token that started a launch never starts a second one while it is within the last `cap` admitted launches | holds over all 25270 states |
| T2 | a refused launch and a repeated token add no entry | holds |
| T3 | the oldest entry is dropped only when the `cap + 1`th launch is admitted | holds |
| T4 | a token whose launch produced no process has no entry and can be retried | holds |
| T5 | the memory never holds more than `cap` entries | holds |
| deadlock | some operation is always enabled | holds |

## Operation partitions and their tests

| Partition | Meaning | Covering test (to write) |
|---|---|---|
| NT1 | a first `new` with a token launches and the entry holds the session | `LaunchOk` |
| NT2 | a repeat while the session runs returns the original session, no second process | `RepeatBound` |
| NT3 | a repeat after the session exited returns the original session, no second process | `RepeatBound` after `ExitLabelled`; the label guard would launch again |
| NT4 | a repeat whose process forked and whose session was never recorded is `rejected` with token and pid | `RepeatUnrecorded` after `LaunchUnrecorded` |
| NT5 | a fork failure leaves the memory as it was, including the oldest entry, and the retry launches | `LaunchForkFails` with the memory full, then the retry and a retry of the oldest token |
| NT6 | a label-taken or config refusal adds no entry, and a retry with the same token launches | `RefuseLabel`, `RefuseConfig` |
| NT7 | a refused or repeated request does not age any entry | `RepeatBound`, `RepeatUnrecorded`, `RefuseLabel` with the memory full, then the oldest token's repeat |
| NT8 | the `cap + 1`th admitted launch drops exactly the oldest entry; its retry starts a new terminal | three launches at `cap = 2`, then a retry of the first token |
| NT9 | a session setup failure after the fork leaves the entry held and the retry refused | `LaunchUnrecorded` then the retry |
| NT10 | a restart clears the memory; a retry then starts the first terminal that exists | `RestartClean` then the retry |
| NT12 | a survivor exits, its token launches a new shell, and a later clean restart ends that new shell (survival is per process, not per token) | `ExitSurvivor`, `LaunchOk`, `RestartClean` |
| NT11 | a surviving shell is logged; a retry can start a second shell (accepted residual) | `RestartSurvivor` then the retry |

## Fidelity variants

Each variant is a copy of the model with one change. The script requires the
named invariant to fail.

| Variant | Change | Fails | Shortest trace found |
|---|---|---|---|
| `request_counted_eviction_buggy` | every request ages entries, not only admitted launches | T3, T1 | 56 and 26 states searched |
| `entry_after_spawn_buggy` | an unrecorded launch adds no entry | T3, T1 | 3 and 23 |
| `entry_kept_after_failed_fork_buggy` | a failed fork keeps its entry | T4, T2 | 12 and 5 |
| `evicted_not_restored_buggy` | a failed fork does not restore the dropped oldest entry | T3, T1 | 11 and 31 |
| `label_guard_buggy` | the repeat guard is the label held by a live session | T1 | 21 |

`label_guard_buggy` fails only after a session exits, which is why NT3 is a
partition of its own.

## Reachability

`scripts/verify_new_tokens_model.sh` reaches, in the intact model: a live shell
whose entry was evicted; a forked token with no session; an exited session whose
entry is held; a full memory; a surviving shell and its retry both live; a clean restart that ends a new shell whose token once had a survivor now gone; and
every operation enabled, `LaunchForkFails` also with the memory full and
`LaunchOk` also for an evicted token.
