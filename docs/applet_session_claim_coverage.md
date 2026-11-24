# Applet session claim coverage

The [model](applet_session_claim.tex) checks that at most one of two starts for
the same session serves at any time. Both provision, open, and try the claim
independently. The model assumes a private, stable directory and the kernel's
nonblocking, per-inode exclusive lock. It does not model permission rejection,
filesystem errors, different applet names, or different sessions.

## Formal checks

From the repository root:

```bash
mkdir -p .tmp/applet-claim-model
model=docs/applet_session_claim.tex
legacy=.tmp/applet-claim-model/legacy.tex
goal='phase(apfirst)=phserving & phase(apsecond)=phserving'
sed 's/^CANONICAL == ztrue$/CANONICAL == zfalse/' "$model" > "$legacy"
fuzz -t "$model" && fuzz -t "$legacy"
probcli="$HOME/Applications/ProB/probcli"
"$probcli" "$model" -model_check -p DEFAULT_SETSIZE 2
"$probcli" "$model" -model_check -p DEFAULT_SETSIZE 2 -nodead -goal "$goal"
"$probcli" "$legacy" -model_check -p DEFAULT_SETSIZE 2 -nodead -goal "$goal"
```

The canonical model visits all 24 states without a deadlock or a safety
violation. The legacy variant reaches the violation: different `TMPDIR`
values give the two starts different inodes, so both acquire a lock.

## Implementation coverage

In `tests/applets/test_claim.py`:

- `test_concurrent_starters_resolve_one_claim_from_separate_tmpdirs` releases
  four independent processes with the same home but distinct temporary
  directories. They enter through `SessionClaim.for_session` with no session
  directory pre-created. One holds the canonical claim; the others refuse.
- `test_a_free_claim_is_taken` and
  `test_a_second_applet_cannot_take_a_claim_that_is_held` cover both results of
  the nonblocking acquisition.
- `test_a_claim_is_free_again_once_its_holder_has_gone` tests that process exit
  releases the lock and permits a subsequent starter.
