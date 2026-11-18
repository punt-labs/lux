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

Stage three adds multiple viewers, per-viewer credit and repaint-on-lag.
The credit model and its coverage report document reset ordering. Automatic
startup and daemon-upgrade persistence remain later work.
