# Published workspace

The root remains `punt-lux`; the other published members are
`packages/punt-lux-client` and `packages/punt-service`. All use `uv_build`.
`uv sync --locked --extra display` installs all three editable distributions.
`make build` builds all three wheels and source distributions. No root
`punt_lux/__init__.py` belongs in any wheel.

## Release versions

All three project versions and both exact internal dependency pins must agree.
`tests/test_workspace.py` enforces this. Do not bump them for ordinary changes.

The shared `punt release run` implementation currently bumps only the root
`pyproject.toml` in Phase 2, before its lock refresh and build. It does not
discover workspace members. The Lux companion operation is:

```bash
make sync-workspace-version
```

Run it on the release branch after the root release bump and before the build
gate; it synchronizes both members and exact root pins, then refreshes `uv.lock`.
Include all three manifests and the lock in the release commit. If the shared
release driver has already reached the build, its version assertion fails
closed: synchronize, commit the mirrors, then resume `punt release run` with
`--resume-from build`. `make sync-workspace-version VERSION=X.Y.Z` can also
perform the three-manifest version change as one operation. Plugin, installer
and changelog mirrors remain the shared Phase 2's responsibility.

Release CI builds all three distributions together and uses two GitHub
environments per index so the two new projects can have distinct pending
Trusted Publishers. Configure each project with owner `punt-labs`, repository
`lux`, workflow `release.yml`, and the environment for the corresponding index:

| Project | TestPyPI | PyPI |
| --- | --- | --- |
| `punt-lux` | `testpypi` | `release` |
| `punt-lux-client` | `testpypi` | `pypi-client` |
| `punt-service` | `testpypi-service` | `release` |

This mapping is Lux's exception to the default environment names in the
shared [Trusted Publishing rule (PL-DI-2)](../.claude/rules/python-distribution.md#pl-di-2-trusted-publishing).
An index allows only one pending project per repository, workflow, and
environment combination; existing publishers can share that combination.

There are no additional CLI entry points in either headless distribution.
Lux's scripts and extras remain in the root product. No publishing action is
required to test the workspace locally.

## Ratchets

Lux scans join `src/punt_lux` and the client portion with `--namespace punt_lux`.
The product-neutral engine is scanned separately with `--namespace punt_service`.
Physical baseline and waiver keys remain repository-relative; module-based
Lux layer declarations retain their existing names. Shared baselines retain
both distributions' physical rows. The neutral OO check permits no improvement
because this extraction should preserve its existing metrics; it still rejects
regressions, and the aggregate product check still requires an improvement.
The suppression tool has one repository snapshot rather than one per namespace:
`update-suppressions` snapshots Lux and checks service without overwriting that
snapshot. Both checks compare live source at the Git base, not snapshot totals.
The new `punt_service` namespace is a first adoption; its two existing source
suppressions are unchanged by extraction.

The development ratchet is pinned to the published `punt-oo-ratchet==0.6.0`
release from PyPI.
