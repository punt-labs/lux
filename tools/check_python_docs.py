"""Check Python comments, docstring arguments, and generated API coverage."""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import subprocess
import sys
import tokenize
import zlib
from itertools import pairwise
from pathlib import Path

from docstring_parser import DocstringStyle, ParseError, parse
from griffe import Alias, Class, GriffeError, GriffeLoader, Object
from markdown import Markdown
from markdown.util import HTML_PLACEHOLDER_RE

_DOC_DIAGNOSTIC = re.compile(r".+:\d+: DOC(\d{3}): (.+)")
_REQUIRED_DOC_CODES = {1, 2, 3, 102, 111, 304}
_OPTIONAL_DOC_CODES = {
    101,
    104,
    105,
    106,
    107,
    108,
    109,
    110,
    *range(201, 204),
    *range(301, 304),
    *range(305, 308),
    *range(401, 406),
    *range(501, 505),
    *range(601, 608),
}
_OMITTED_ARGS = "Arguments in the function signature but not in the docstring:"
_STALE_ARGS = "Arguments in the docstring but not in the function signature:"
_ARGS_HEADER = re.compile(r"^(?:Args|Arguments|Parameters|Params):[ \t\r\f\v]*$", re.M)
_TRACKER_REFERENCE = re.compile(
    r"(?<![\w-])(?:PL-\d+|lux-[a-z0-9]{4}(?:\.\d+)*)(?![\w-])"
    r"|\b(?:PR|issue|pull request)\s+#\d+\b"
    r"|\blinear\.app/[^/\s]+/issue/[^/\s]+"
    r"|\bgithub\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/\d+\b",
    re.IGNORECASE,
)
_API_MODULES = ("punt_lux", "punt_lux.client", "punt_lux.hub_client")
_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


def _expected_api_symbols() -> set[str]:
    symbols: set[str] = set(_API_MODULES)
    for module in _API_MODULES:
        path = _SOURCE_ROOT.joinpath(*module.split("."))
        file = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
        with tokenize.open(file) as source:
            body = ast.parse(source.read(), filename=str(file)).body
        for item in body:
            if isinstance(item, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in item.targets
            ):
                exports = item.value
                if not isinstance(exports, ast.List | ast.Tuple):
                    raise ValueError(f"{file}: expected a literal __all__")
                for name in exports.elts:
                    if not isinstance(name, ast.Constant) or not isinstance(
                        name.value, str
                    ):
                        raise ValueError(f"{file}: expected string exports in __all__")
                    symbols.add(f"{module}.{name.value}")
                break
        else:
            raise ValueError(f"{file}: expected a public export list")
    return symbols


def doclint_findings(returncode: int, output: str) -> list[str]:
    """Retain violations that are incompatible with selective Google-style docs."""
    lines = [line for line in output.splitlines() if line.strip()]
    if returncode == 0 and not lines:
        return []
    if returncode != 1 or not lines:
        return [f"pydoclint failed unexpectedly (exit {returncode}): {output!r}"]

    findings: list[str] = []
    for line in lines:
        match = _DOC_DIAGNOSTIC.fullmatch(line)
        if match is None:
            findings.append(f"Unrecognized pydoclint output: {line}")
            continue
        code, message = int(match[1]), match[2]
        if code == 103:
            # A partial Args section is valid unless it names an unknown parameter.
            if _STALE_ARGS in message or _OMITTED_ARGS not in message:
                findings.append(line)
        elif code not in _OPTIONAL_DOC_CODES:
            findings.append(
                line
                if code in _REQUIRED_DOC_CODES
                else f"Unknown pydoclint code: {line}"
            )
    return findings


def tracker_references(source: str, filename: str) -> list[str]:
    """Find tracker references in Python comments and actual docstrings."""
    prose = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        if (docstring := ast.get_docstring(node, clean=False)) is not None:
            prose.append((node.body[0].lineno, docstring))
        if isinstance(node, ast.Module | ast.ClassDef) or node.name == "__init__":
            prose.extend(
                (string.lineno, string.value.value)
                for assignment, string in pairwise(node.body)
                if isinstance(assignment, ast.Assign | ast.AnnAssign | ast.TypeAlias)
                and isinstance(string, ast.Expr)
                and isinstance(string.value, ast.Constant)
                and isinstance(string.value.value, str)
            )

    return [
        f"{filename}:{line}: remove tracker reference {match[0]!r} from code prose"
        for line, content in sorted(prose)
        for match in _TRACKER_REFERENCE.finditer(content)
    ]


def missing_api_symbols(inventory: bytes) -> frozenset[str]:
    """Check that the generated Sphinx inventory contains the expected Python API."""
    header, _, _, compression, body = inventory.split(b"\n", 4)
    if header != b"# Sphinx inventory version 2" or b"zlib" not in compression:
        raise ValueError("Expected a version 2 Sphinx inventory")
    published: set[str] = set()
    for line in zlib.decompress(body).decode().splitlines():
        name, role, _, _, _ = line.split(maxsplit=4)
        if role.startswith("py:"):
            published.add(name)
    return frozenset(_expected_api_symbols() - published)


def _raise_walk_error(error: OSError) -> None:
    raise error


def _python_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix in {".py", ".pyi"}:
        return [root]
    if not root.is_dir():
        raise ValueError(f"Not a Python source path: {root}")
    return sorted(
        directory / name
        for directory, _, names in root.walk(on_error=_raise_walk_error)
        for name in names
        if Path(name).suffix in {".py", ".pyi"}
    )


def _public_members(cls: Object | Alias) -> list[Object | Alias]:
    members = [
        member
        for name, member in cls.members.items()
        if not name.startswith("_")
        and (member.is_class or member.is_function or "property" in member.labels)
    ]
    findings = [member for member in members if not member.has_docstring]
    for member in members:
        if member.is_class:
            findings.extend(_public_members(member))
    return findings


def public_doc_findings(source: Path, modules: tuple[str, ...]) -> list[str]:
    """Check exported library objects and registered tools without importing Lux."""
    loader = GriffeLoader(search_paths=[source], allow_inspection=False)
    for package in sorted({name.split(".")[0] for name in modules}):
        loader.load(package)
    loader.resolve_aliases(implicit=False, external=False)
    missing: set[str] = set()
    for name in modules:
        module = loader.modules_collection[name]
        if module.exports is None:
            raise ValueError(f"{name}: expected a public export list")
        for symbol in sorted(module.exports):
            member = module[symbol]
            if not member.has_docstring:
                missing.add(member.canonical_path)
            if member.is_class:
                missing.update(obj.canonical_path for obj in _public_members(member))

    for path in _python_files(source):
        with tokenize.open(path) as file:
            tree = ast.parse(file.read(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not ast.get_docstring(node) and any(
                ast.unparse(dec.func if isinstance(dec, ast.Call) else dec)
                == "mcp.tool"
                for dec in node.decorator_list
            ):
                missing.add(f"{path}:{node.lineno}: {node.name}")
    return [f"Missing public docstring: {name}" for name in sorted(missing)]


def _without_fenced_examples(docstring: str) -> str:
    markdown = Markdown(extensions=["fenced_code"])
    fenced_code = markdown.preprocessors["fenced_code_block"]
    lines = fenced_code.run(docstring.split("\n"))
    return "\n".join(line for line in lines if not HTML_PLACEHOLDER_RE.fullmatch(line))


def _uses_only_new(node: ast.ClassDef) -> bool:
    if node.keywords or any(
        not isinstance(base, ast.Name) or base.id != "object" for base in node.bases
    ):
        return False
    for decorator in node.decorator_list:
        # A decorator may synthesize __init__; require a static opt-out.
        if (
            not isinstance(decorator, ast.Call)
            or ast.unparse(decorator.func) not in {"dataclass", "dataclasses.dataclass"}
            or not any(
                keyword.arg == "init"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                for keyword in decorator.keywords
            )
        ):
            return False
    methods = {
        item.name
        for item in node.body
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    return "__new__" in methods and "__init__" not in methods


def _class_constructors(container: Object | Alias) -> dict[int, set[str]]:
    constructors: dict[int, set[str]] = {}
    for member in container.members.values():
        if isinstance(member, Class):
            docstring = member.docstring
            if (
                docstring is not None
                and docstring.lineno is not None
                and "__init__" in member.all_members
            ):
                constructors[docstring.lineno] = {
                    param.name for param in list(member.parameters)[1:]
                }
            constructors.update(_class_constructors(member))
    return constructors


def _load_class_constructors(path: Path) -> dict[int, set[str]]:
    path = path.resolve()
    root = path.parent
    while (root / "__init__.py").is_file():
        root = root.parent
    parts = path.relative_to(root).with_suffix("").parts
    module = ".".join(parts[:-1] if path.stem == "__init__" else parts)
    loader = GriffeLoader(search_paths=[root], allow_inspection=False)
    return _class_constructors(loader.load(module))


def _argument_doc_findings(path: Path) -> list[str]:
    with tokenize.open(path) as source:
        tree = ast.parse(source.read(), filename=str(path))
    findings: list[str] = []
    constructors: dict[int, set[str]] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not (docstring := ast.get_docstring(node)):
            continue
        docstring = _without_fenced_examples(docstring)
        if len(_ARGS_HEADER.findall(docstring)) > 1:
            findings.append(f"{path}:{node.lineno}: repeated Args section")
            continue
        try:
            params = parse(docstring, style=DocstringStyle.GOOGLE).params
        except ParseError:
            # pydoclint reports malformed sections separately.
            continue
        if isinstance(node, ast.ClassDef) and params:
            if _uses_only_new(node):
                findings.append(
                    f"{path}:{node.lineno}: document constructor arguments on __new__"
                )
            elif not any(
                isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__"
                for stmt in node.body
            ):
                # pydoclint only checks class Args against a source constructor.
                # Use the same static signatures as the API docs for generated ones.
                if constructors is None:
                    constructors = _load_class_constructors(path)
                if (valid := constructors.get(node.body[0].lineno)) is not None:
                    names = {p.arg_name.lstrip("*") for p in params}
                    findings.extend(
                        f"{path}:{node.lineno}: documented constructor parameter "
                        f"{name!r} does not exist"
                        for name in sorted(names - valid)
                    )
        seen: set[str] = set()
        for param in params:
            name = param.arg_name.lstrip("*")
            if name in seen:
                findings.append(f"{path}:{node.lineno}: repeated Args entry {name!r}")
            seen.add(name)
    return findings


def _check_docstrings(source: Path) -> list[str]:
    files = _python_files(source)
    if not files:
        return [f"No Python source files found: {source}"]
    env = dict(os.environ)
    env.pop("RUST_LOG", None)
    # FastMCP depends on the upstream docstring_parser namespace; pydoclint
    # needs its fork. Keep the two distributions in separate environments.
    env["UV_NO_SYNC"] = "false"
    env["UV_PROJECT_ENVIRONMENT"] = str(_SOURCE_ROOT.parent / ".tmp" / "doclint-venv")
    result = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "--quiet",
            "--only-group",
            "doclint",
            "pydoclint",
            "--config",
            "pyproject.toml",
            "--quiet",
            "--exclude",
            "",
            "--show-filenames-in-every-violation-message",
            "true",
            *[str(path.resolve()) for path in files],
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    findings = doclint_findings(result.returncode, result.stdout)
    if not findings:
        for path in files:
            findings.extend(_argument_doc_findings(path))
    return findings


def _check_comments(roots: list[Path]) -> list[str]:
    files = {path for root in roots for path in _python_files(root)}
    findings: list[str] = []
    for path in sorted(files):
        with tokenize.open(path) as source:
            findings.extend(tracker_references(source.read(), str(path)))
    return findings


def main() -> int:
    """Run a documentation gate and fail on violations or tool errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="gate", required=True)
    commands.add_parser("docstrings").add_argument("source", type=Path)
    commands.add_parser("public").add_argument("source", type=Path)
    commands.add_parser("comments").add_argument("roots", nargs="+", type=Path)
    commands.add_parser("api").add_argument("inventory", type=Path)
    args = parser.parse_args()
    try:
        if args.gate == "docstrings":
            findings = _check_docstrings(args.source)
        elif args.gate == "public":
            findings = public_doc_findings(args.source, _API_MODULES)
        elif args.gate == "comments":
            findings = _check_comments(args.roots)
        else:
            missing = missing_api_symbols(args.inventory.read_bytes())
            findings = [
                f"Missing generated API entry: {name}" for name in sorted(missing)
            ]
    except (
        GriffeError,
        KeyError,
        OSError,
        SyntaxError,
        ValueError,
        tokenize.TokenError,
        zlib.error,
    ) as error:
        findings = [str(error)]
    for finding in findings:
        print(finding.replace("\r", r"\r").replace("\n", r"\n"), file=sys.stderr)
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
