"""Renamed source files preserve the layer baseline without accepting new edges."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.layer_baseline import LayerBaseline
from tools.layer_renames import LayerRenames


@pytest.mark.parametrize(
    "name_status",
    ["", "R100\0src/punt_lux/old.txt\0src/punt_lux/new.txt\0"],
)
def test_empty_and_non_python_renames_leave_edges_unchanged(name_status: str) -> None:
    edges = frozenset({"punt_lux.old → punt_lux.cli"})
    assert LayerRenames(name_status).apply(edges) == edges


def test_renames_module_and_package_endpoints_not_similar_names() -> None:
    renames = LayerRenames(
        "R090\0src/punt_lux/old/__init__.py\0src/punt_lux/new/__init__.py\0"
        "R095\0src/punt_lux/old/leaf.py\0src/punt_lux/new/leaf.py\0"
    )
    assert renames.apply(
        frozenset(
            {
                "punt_lux.old → punt_lux.old.leaf",
                "punt_lux.old.leaf → punt_lux.cli",
                "punt_lux.old.sibling → punt_lux.cli",
            }
        )
    ) == frozenset(
        {
            "punt_lux.new → punt_lux.new.leaf",
            "punt_lux.new.leaf → punt_lux.cli",
            "punt_lux.old.sibling → punt_lux.cli",
        }
    )


def test_malformed_name_status_is_not_silently_accepted() -> None:
    with pytest.raises(ValueError, match="zip"):
        LayerRenames("R100\0src/punt_lux/old.py\0")


@pytest.mark.parametrize("explicit", [False, True])
def test_git_rename_preserves_baseline_but_rejects_new_edges(
    tmp_path: Path, explicit: bool
) -> None:
    package = tmp_path / "src" / "punt_lux"
    package.mkdir(parents=True)
    old = package / "old.py"
    old.write_text("VALUE = 42\n")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(["punt_lux.kernel.tracing → punt_lux.old"]))
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
    subprocess.run([git, "add", "src", "baseline.json"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            git,
            "-c",
            "user.name=Layer Test",
            "-c",
            "user.email=layer@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "base",
        ],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [git, "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=tmp_path,
        check=True,
    )
    old.rename(package / "new.py")
    subprocess.run([git, "add", "src"], cwd=tmp_path, check=True)
    store = LayerBaseline(baseline)
    base_ref = "HEAD" if explicit else ""
    expected = frozenset({"punt_lux.kernel.tracing → punt_lux.new"})
    assert store.read(base_ref) == expected
    store.check(expected, base_ref)
    with pytest.raises(ValueError, match="1 added edges"):
        store.check(expected | {"punt_lux.kernel.tracing → punt_lux.cli"}, base_ref)
