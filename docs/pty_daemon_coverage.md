# Daemon lifecycle: model and implementation coverage

## Lifetime arbitration

Every `PtyServer` owns a nonblocking exclusive flock before stale cleanup,
bind and listen. The claim remains held through endpoint and session cleanup.
The kernel releases it on crash. The lock inode is intentionally never deleted:
unlinking it can let a waiter on the old inode race a newly opened lock file.

Private runtime directory, lock, log and socket checks reject foreign owners,
symlinks and writable/nonregular locations. Stale cleanup removes only an
owned socket with refused connection and unchanged device/inode. A live
unguarded listener is preserved too; other connection errors are not treated
as permission to unlink. Same-UID processes remain the local trust boundary.

## Formal checks

```sh
timeout 30 fuzz -t docs/pty_daemon.tex
timeout 120 probcli docs/pty_daemon.tex -model_check -p DEFAULT_SETSIZE 2 \
  -goal 'card(claim)>1 or card(listeners)>1 or listeners /<: claim'
timeout 120 probcli docs/pty_daemon.tex -model_check -p DEFAULT_SETSIZE 2 \
  -goal 'unsafeStop=yes'
```

All **53 states / 208 transitions** are visited with no counterexample. Safety
is expressed as a violation goal, not a state predicate. Mutations expose:

- Acquire without checking the empty claim: five-step trace reaches an
  existing listener whose claim has been replaced by another starter.
- Idle shutdown without checking empty work: eight-step trace stops with
  a client still attached.

The model abstracts time and OS lock ownership. It does not prove fairness,
credential validation, spawn behavior, native cleanup, or daemon-crash program
survival. Only Display-crash survival is a goal of this step.

## Implementation evidence

- Unit tests hold the claim before a listener exists and reject a contender.
- Owned stale socket is reclaimed; live unguarded listener and regular files
  are preserved. The reusable lock remains after close.
- Idle timer requires a continuous empty interval and resets on either a
  client or a session. Exited screens remain sessions until explicit kill.
- Integration starts two detached launchers against one path; one loses the
  claim, the winner accepts hello, and orderly stop removes its socket.
- Real short-idle server stays alive with an attached client and exits after
  it disconnects, removing the socket.
- A production Display-side RemotePool starts a missing daemon, receives
  output, closes without stopping the owner, and reconnects for explicit kill.

The default idle interval is 30 seconds, only when there are no clients and no
sessions. Launch uses the current interpreter, argument-vector posix_spawn,
setsid and detached stdio. UI does not wait for launch; startup children are
reaped with WNOHANG and never killed by Display close. Spawn retry is bounded
by a cooldown and one unreaped child per launcher. Lock/log files persist as
inert private runtime state; socket and child cleanup are the transient goal.
