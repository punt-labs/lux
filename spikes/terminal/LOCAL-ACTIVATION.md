# Local activation and loaded/stopped Display startup fix

## Approved runtime switch

After the local wheel install, the operator explicitly approved shutting down
the normal Hub, switching to this build and running Terminal enable.

- Previous Hub **40752** stopped and was observed to exit before starting another.
- Installed-wheel Hub **94061** started on loopback port 8430.
- `lux terminal enable` installed/started the local LaunchAgent
  `com.punt-labs.luxd-pty` from `~/.local/bin/luxd-pty`.
- Owner **94068**, parent-watched menu helper **94074**.
- Menu contains `Clients -> luxd-pty -> Terminal`, alongside existing Vox/Music
  entries. Registration has zero PTY sessions before a user launches Terminal.

This supersedes LOCAL-WHEEL-INSTALL.md's historical pending-approval note. The
installed tool uses the locally built branch wheel; this is not a main merge.

## Display startup failure, diagnosed

Both operator and assistant saw `lux display start` fail with launchctl bootstrap
rc 5. Inspection showed valid plist/config and an **already-loaded, not-running**
Display job with last exit code 0. Crash-only KeepAlive intentionally leaves a
cleanly exited Display stopped while retaining its launchd registration.

The old backend always bootstrapped an installed plist. A second bootstrap of
an existing registration fails; the problem was not missing permission or a need
to run as root. A direct non-destructive `launchctl kickstart` of the existing
job started installed-wheel Display **95424**. Hub link became connected_active;
Display info reports 26 element kinds, and Terminal remains enabled.

## Source fix and verification

Launchd start now distinguishes registration from config-file existence:

- loaded job: `kickstart` **without -k**, starting a cleanly stopped job and
  leaving any running process alone;
- unloaded job: bootstrap the installed plist;
- failed kickstart: return failure, no destructive bootout/bootstrap fallback.

Tests cover Display and Hub registered jobs, unloaded bootstrap and failure
propagation. Existing install/KeepAlive tests remain. Reused target/config
properties keep supervisor identity/config roles clear.

Scoped make check includes only the targeted backend file in addition to prior
scope: **858 tests pass**, 22 integrations deselected. Separately all **22
integrations pass** in sequential isolated sets. Whole typing/lint and all OO/
coupling/suppression gates pass without threshold relaxation; source suppressions
remain 123. The full macOS suite is still deliberately unrun.

The operational kickstart restored the window before this source fix was built.
The follow-up wheel installs the CLI fix without restarting the currently running
Hub/Display/Terminal processes or ending user shells. Runtime/installed verification
is recorded with the local artifact provenance, not inferred solely from tests.
