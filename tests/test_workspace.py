"""Published distribution versions, neutral imports and source discovery."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

from tools.prove_workspace_wheels import prove
from tools.source_tree import SourceTree
from tools.workspace_graph import WorkspaceGraph
from tools.workspace_version import synchronize

ROOT = Path(__file__).resolve().parents[1]


def test_published_versions_and_exact_dependency_pins_agree() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    for name in ("punt-lux-client", "punt-service"):
        member = tomllib.loads(
            (ROOT / "packages" / name / "pyproject.toml").read_text()
        )["project"]
        assert member["version"] == project["version"]
        assert f"{name}=={project['version']}" in project["dependencies"]


def test_service_has_only_standard_library_and_own_imports() -> None:
    project = tomllib.loads(
        (ROOT / "packages/punt-service/pyproject.toml").read_text()
    )["project"]
    assert project["dependencies"] == []
    modules = SourceTree(ROOT / "src").modules("punt_service")
    assert modules
    for name, path in modules.items():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or "punt_service"]
            else:
                continue
            for imported in imports:
                assert imported.split(".")[0] in {
                    *sys.stdlib_module_names,
                    "punt_service",
                }, (name, imported)


def _manifests(root: Path) -> list[Path]:
    paths = [
        root / "pyproject.toml",
        *(
            root / "packages" / name / "pyproject.toml"
            for name in ("punt-lux-client", "punt-service")
        ),
    ]
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        text = '[project]\nversion = "1.2.3"\n'
        if index == 0:
            text += 'dependencies = ["punt-lux-client==1.2.3", "punt-service==1.2.3"]\n'
        path.write_text(text)
    return paths


def test_release_operation_updates_all_versions_and_pins(tmp_path: Path) -> None:
    paths = _manifests(tmp_path)
    assert synchronize(tmp_path, "2.0.0") == paths
    assert all(
        tomllib.loads(path.read_text())["project"]["version"] == "2.0.0"
        for path in paths
    )
    assert synchronize(tmp_path) == []


@pytest.mark.parametrize("error", ["version", "pin", "member"])
def test_invalid_release_input_never_partially_writes(
    tmp_path: Path, error: str
) -> None:
    paths = _manifests(tmp_path)
    if error == "pin":
        paths[0].write_text(
            paths[0].read_text().replace("punt-service==1.2.3", "punt-service>=1")
        )
    elif error == "member":
        paths[-1].unlink()
    before = {path: path.read_text() for path in paths if path.exists()}
    with pytest.raises((ValueError, FileNotFoundError)):
        synchronize(tmp_path, "invalid" if error == "version" else "2.0.0")
    assert {path: path.read_text() for path in before} == before


def test_empty_source_and_graph_are_empty(tmp_path: Path) -> None:
    assert SourceTree(tmp_path / "src").modules() == {}
    assert SourceTree(tmp_path / "src").files() == {}
    assert WorkspaceGraph([tmp_path / "punt_lux"]).snapshot()["edges"] == []


def test_namespace_file_paths_span_members_and_reject_conflicts(tmp_path: Path) -> None:
    product = tmp_path / "src" / "punt_lux"
    client = tmp_path / "packages" / "client" / "src" / "punt_lux"
    service = tmp_path / "packages" / "service" / "src" / "punt_service"
    for root in (product, client / "client", service):
        root.mkdir(parents=True)
    (product / "server.py").touch()
    (client / "client" / "__init__.py").touch()
    (service / "__init__.py").touch()
    tree = SourceTree(tmp_path / "src")
    assert tree.files() == {
        "server.py": product / "server.py",
        "client/__init__.py": client / "client" / "__init__.py",
    }
    assert tree.files("punt_service") == {"__init__.py": service / "__init__.py"}
    (client / "server.py").touch()
    with pytest.raises(ValueError, match="Duplicate module"):
        tree.files()


@pytest.mark.parametrize("count", [0, 2])
def test_wheel_proof_rejects_missing_or_ambiguous_artifacts(
    tmp_path: Path, count: int
) -> None:
    for version in range(count):
        (tmp_path / f"punt_lux-{version}.whl").touch()
    with pytest.raises(ValueError, match="Expected one punt_lux wheel"):
        prove(tmp_path, tmp_path / "environments")
    assert not (tmp_path / "environments").exists()


def test_cross_root_edges_and_duplicate_rejection(tmp_path: Path) -> None:
    roots = [tmp_path / member / "punt_lux" for member in ("product", "client")]
    for root in roots:
        root.mkdir(parents=True)
    (roots[0] / "app.py").write_text("from punt_lux.client import Client\n")
    (roots[1] / "client.py").write_text("")
    assert WorkspaceGraph(roots).snapshot()["edges"] == [
        ["punt_lux.app", "punt_lux.client"]
    ]
    (roots[1] / "app.py").write_text("")
    with pytest.raises(ValueError, match="Duplicate module"):
        WorkspaceGraph(roots)
