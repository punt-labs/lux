# Terminal peer protocol: model and coverage

Fuzz accepts `pty_peer.tex`. ProB visits all **49 states and 176 transitions**
for both safety goals:

```sh
timeout 30 fuzz -t docs/pty_peer.tex
timeout 120 probcli docs/pty_peer.tex -model_check \
  -p DEFAULT_SETSIZE 2 -goal 'created /<: authorized'
timeout 120 probcli docs/pty_peer.tex -model_check \
  -p DEFAULT_SETSIZE 2 -goal '#p.(p:created & phase(p)=accepted)'
```

No violating state is found. Weakening `CreateProgram` to allow any phase
produces the trace `Init -> CreateProgram(absent peer)`, without authentication
or negotiation. The model does not assume the safety properties as predicates.

| Partition | Code/test evidence |
| --- | --- |
| Kernel UID, not a caller claim | Real socket-pair UID query and injected foreign-UID rejection |
| Private endpoint permissions | Endpoint mode and unsafe-directory tests |
| Never replace another node during startup | Existing-file test |
| Never unlink a replacement during shutdown | Replacement-node test |
| No program before hello | Independent-daemon integration test |
| Version mismatch leaves peer unready | Independent-daemon integration test |
| Disconnect removes viewer, not process | Independent-daemon test reconnects to the same PID and screen |
| Headless native package | Import test blocks GUI dependency modules |
| Malformed frames and short writes | Framing tests and bounded writer tests |

The credit model/coverage documents reset ordering. Lazy startup, lifetime
claims, safe stale reclamation and empty-only idle exit are implemented and
covered in pty_daemon_coverage.md. Daemon-upgrade program persistence is not a
goal of this step; only Display restart/crash preserves held programs.
