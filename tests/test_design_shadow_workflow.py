"""Exercise the report-only design workflow with normal, empty and error output."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ratchets.yml"
STEP = "Design ratchet (shadow, report only)"


def test_full_report_includes_non_gating_design_scan() -> None:
    report = (
        (ROOT / "Makefile")
        .read_text()
        .split("\nreport:", 1)[1]
        .split("\nformat:", 1)[0]
    )
    assert "\t-uv run --extra display oo-ratchet design src/punt_lux/\n" in report


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("punt_lux.luxd", "entry"),
        ("punt_lux.client.facade", "adapters"),
        ("punt_lux.client_host", "domain"),
        ("punt_lux.domain.hub.display_link", "adapters"),
        ("punt_lux.domain.hub.cross_host_link", "adapters"),
        ("punt_lux.domain.hub.hub_display", "domain"),
        ("punt_lux.operations", "application"),
        ("punt_lux.operations.models.common", "domain"),
        ("punt_lux.display.render_loop", "adapters"),
        ("punt_lux.service._backends", "adapters"),
        ("punt_lux.bounded_send", "adapters"),
        ("punt_lux.cli_identity", "adapters"),
        ("punt_lux.log_level", "adapters"),
        ("punt_lux.wire.model", "adapters"),
        ("punt_lux.wire.model.connection", "adapters"),
        ("punt_lux.wire.model.renderers.recording", "adapters"),
        ("punt_lux.wire.model.elements", "domain"),
        ("punt_lux.wire.model.messages", "domain"),
        ("punt_lux.wire", "domain"),
        ("punt_lux.kernel.connection_id", "domain"),
        ("punt_lux.kernel.programmer_error", "domain"),
        ("punt_lux.protocol.pty.frames", "domain"),
        ("punt_lux.ptyd.input_buffer", "adapters"),
        ("punt_lux.ptyd.leader_status", "adapters"),
        ("punt_lux.domain.hub.handshake_outcome", "adapters"),
        ("punt_lux.undeclared", None),
    ],
)
def test_design_layer_boundaries(
    module: str,
    expected: str | None,  # None means the module matches no layer.
) -> None:
    layers = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["oo-ratchet"][
        "layers"
    ]
    actual = next(
        (
            layer
            for layer, patterns in layers.items()
            if any(fnmatchcase(module, pattern) for pattern in patterns)
        ),
        None,
    )
    assert actual == expected


def shadow_step() -> str:
    """Extract the actual reporting step, excluding YAML comments and later steps."""
    source = "\n".join(
        line
        for line in WORKFLOW.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    return source.split(f"      - name: {STEP}\n", 1)[1].split("\n      - ", 1)[0]


def test_shadow_is_a_pr_report_not_a_gate() -> None:
    source = WORKFLOW.read_text()
    assert source.index('- name: "Run coupling ratchet') < source.index(
        f"- name: {STEP}"
    )
    step = shadow_step()
    assert "if: ${{ !cancelled() && github.event_name == 'pull_request' }}" in step
    assert "continue-on-error: true" in step
    assert "DESIGN_BASE: origin/${{ github.base_ref }}" in step
    assert "${{" not in step.split("run: |\n", 1)[1]
    check = next(
        line
        for line in (ROOT / "Makefile").read_text().splitlines()
        if line.startswith("check:")
    )
    assert "design-shadow" not in check
    assert "DESIGN_BASE ?= origin/main" in (ROOT / "Makefile").read_text()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("status", "output"),
    [(0, "neutral\n"), (0, ""), (2, "FAIL: invalid reference\n")],
)
def test_shadow_publishes_success_empty_and_error_reports(
    tmp_path: Path, status: int, output: str
) -> None:
    uv = tmp_path / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" > "$ARGV_LOG"\n'
        'printf "%s" "$SHADOW_OUTPUT"\nexit "$SHADOW_STATUS"\n'
    )
    uv.chmod(0o755)
    summary = tmp_path / "summary.md"
    summary.write_text("Earlier step\n")
    argv_log = tmp_path / "argv.txt"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
        "DESIGN_BASE": "origin/other-base",
        "ARGV_LOG": str(argv_log),
        "SHADOW_OUTPUT": output,
        "SHADOW_STATUS": str(status),
    }
    script = textwrap.dedent(shadow_step().split("run: |\n", 1)[1])
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert argv_log.read_text().strip() == (
        "run --extra display oo-ratchet design src/punt_lux "
        "--shadow-check origin/other-base"
    )
    report = summary.read_text()
    assert report.startswith(f"Earlier step\n### {STEP}")
    assert report == "Earlier step\n" + result.stdout
    assert report.endswith("```\n")
    assert output in report
