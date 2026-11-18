# Local wheel build and install — run 1 of the requested six-run follow-up

## Artifact and installed package

- Code revision built: `99b23e6` on `spike/terminal-ghostty`.
- Wheel/source build succeeded with uv 0.7.13.
- Artifact directory:
  `~/Coding/punt-labs/.tmp/lux-terminal-install/99b23e6/dist/`.
- Wheel: `punt_lux-0.33.1-py3-none-any.whl`.
- SHA-256: `1a558f571f523bf2b889a5512f1bb6f842380350624a09a0e4102b627526ad93`.
- Installed with `uv tool install --force --python 3.14`, wheel extras
  `[display,terminal]`, and constraints preserving existing dependency versions.
- Existing tool entry points remain; new `~/.local/bin/luxd-pty` is present.
- Tool environment:
  `~/.local/share/uv/tools/punt-lux/`.
- Receipt/direct_url points to this local wheel, not the old missing migration
  wheel or editable source. Version stays 0.33.1; artifact URL/hash identifies it.

## Preservation and rollback material

Before install, copied the complete 201 MiB tool environment and saved its
receipt/dependency freeze under the private local directory:

`~/Coding/punt-labs/.tmp/lux-terminal-install/99b23e6/backup/`.

The prior receipt referenced a migration wheel that no longer exists, so merely
saving its filename would not have been rollback material. The environment copy
preserves the prior installed distribution. Do not restore it while mutating
service registrations or confuse the backup receipt with a fresh source build.

Freeze comparison: only punt-lux's artifact URL changed and pyghostty 0.1.4 was
added. Existing display/core dependencies stayed at their installed versions.
No gpg/password-store files or other tool installations were changed.

## Installed-environment checks

- `lux terminal --help`: enable/disable/restart/status available.
- `luxd-pty --help`: socket and no-menu options available.
- `lux terminal status`: not running; read-only, no enablement action.
- Isolated installed Python (`-I`) imports punt_lux from the tool environment,
  pyghostty 0.1.4 and existing imgui-bundle 1.92.900.
- Fresh installed executable smoke, not the clone's venv/test client:
  typed hello, create, output, binary snapshot, disconnect, reattach, explicit kill.
  Program PID **90881** is unchanged across reconnect; owner **90880** stops cleanly.
  Marker `INSTALLED_WHEEL_READY` is retained; listing is empty after kill.
- Temporary owner/socket/program/instance are cleaned. No PTY test process remains.

## Runtime activation is deliberately pending

Normal Hub PID **40752** remains running; no normal Display was running at the
inspection. Installing the wheel does not reload already-imported Hub code.
The existing Hub predates this terminal implementation and must be restarted
before normal Terminal rendering/menu activation can be considered coherent.

No `lux terminal enable`, service registration change, normal Hub restart or
normal Display start was performed. Previous instruction not to disturb normal
Lux services remains in force beyond the explicitly requested wheel install.

Next operator-approved activation:

1. Restart the normal Hub onto the installed wheel.
2. Enable Terminal on this machine through the local supervisor command.
3. Start/attach the intended Display and hand-test the daemon-owned menu item.
4. Verify same-PID close/reopen/restart, and record actual manual input behavior.

This installation is not a main merge or shipping approval. Prior keyboard/pixel,
soak/platform, broader macOS suite and independent-review gaps remain stated in
STEP4-REVIEW.md; source validation at the built revision was 850 focused tests,
22 isolated integrations, all quality gates and 123 source suppressions.
