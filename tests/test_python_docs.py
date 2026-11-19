"""Exercise Python documentation gates with passing and failing inputs."""

from __future__ import annotations

import subprocess
import sys
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tools.check_python_docs import (
    doclint_findings,
    main,
    missing_api_symbols,
    public_doc_findings,
    tracker_references,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_ROOT = Path(__file__).resolve().parents[1]
_TOOL = _ROOT / "tools" / "check_python_docs.py"


def _run_doclint(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_TOOL), "docstrings", str(path)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("source", "violation"),
    [
        (
            '''def f(timeout: int) -> int:
    """Return the timeout."""
    return timeout
''',
            "",
        ),
        (
            '''def f(path: str, timeout: int) -> str:
    """Read a file.

    Args:
        timeout: Limit the wait in seconds.
    """
    return path
''',
            "",
        ),
        (
            '''def f(timeout: int) -> int:
    """Read a file.

    Args:
        deadline: Limit the wait in seconds.
    """
    return timeout
''',
            "DOC103",
        ),
        (
            '''def f(timeout: int) -> int:
    """Read a file.

    Args:
        timeout: Limit the wait in seconds.
        deadline: Limit the wait before retrying.
    """
    return timeout
''',
            "DOC102",
        ),
        (
            '''def f(timeout: int) -> int:
    """Read a file.

    Args:
        timeout (int): Limit the wait in seconds.
    """
    return timeout
''',
            "DOC111",
        ),
        (
            '''def f(timeout: int) -> int:
    """Read a file.

    :param deadline: Limit the wait in seconds.
    """
    return timeout
''',
            "DOC003",
        ),
        (
            '''class Reader:
    """Read a file."""

    def __init__(self, timeout: int) -> None:
        """Set up the reader.

        Args:
            deadline: Limit the wait in seconds.
        """
''',
            "DOC103",
        ),
        (
            '''class Reader:
    """Read a file."""

    def __new__(cls, timeout: int) -> Reader:
        """Create a reader.

        Args:
            deadline: Limit the wait in seconds.
        """
        return super().__new__(cls)
''',
            "DOC103",
        ),
        (
            '''class Reader:
    """Read a file.

    Args:
        deadline: Limit the wait in seconds.
    """

    def __new__(cls, timeout: int) -> Reader:
        """Create a reader."""
        return super().__new__(cls)
''',
            "document constructor arguments on __new__",
        ),
        (
            '''class Reader:
    """Read a file."""

    def __new__(cls, timeout: int) -> Reader:
        """Create a reader.

        Args:
            timeout: Limit the wait in seconds.
        """
        return super().__new__(cls)
''',
            "",
        ),
        (
            '''def f(timeout: int) -> int:
    """Return the timeout.

    Args:
        malformed argument entry without a colon
    """
    return timeout
''',
            "DOC001",
        ),
        ("def f(:\n", "DOC002"),
    ],
)
def test_pydoclint_gate(tmp_path: Path, source: str, violation: str) -> None:
    path = tmp_path / "example.py"
    path.write_text(source, encoding="utf-8")
    result = _run_doclint(path)
    assert result.returncode == (1 if violation else 0), result.stderr
    assert violation in result.stderr if violation else not result.stderr


@pytest.mark.parametrize(
    ("returncode", "output"),
    [
        (0, "unexpected output"),
        (1, ""),
        (1, "tool crashed"),
        (1, "src/test.py:2: DOC999: Unrecognized diagnostic"),
        (1, "src/test.py:2: DOC103: Unrecognized argument mismatch format"),
        (2, "invocation error"),
    ],
)
def test_doclint_fails_closed(returncode: int, output: str) -> None:
    assert doclint_findings(returncode, output)


def test_missing_executable_fails_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    path = tmp_path / "example.py"
    path.write_text('"""A module."""\n', encoding="utf-8")
    result = _run_doclint(path)
    assert result.returncode == 1
    assert "uv" in result.stderr


def test_doclint_checks_paths_containing_tox(tmp_path: Path) -> None:
    directory = tmp_path / "checkout.tox"
    directory.mkdir()
    path = directory / "example.py"
    path.write_text(
        '''def f(timeout: int) -> int:
    """Return the timeout.

    Args:
        deadline: The obsolete parameter in seconds.
    """
    return timeout
''',
        encoding="utf-8",
    )
    result = _run_doclint(directory)
    assert result.returncode == 1
    assert "DOC103" in result.stderr


@pytest.mark.parametrize(
    ("parameter", "valid"), [("timeout", True), ("deadline", False), ("state", False)]
)
def test_doclint_checks_dataclass_constructor(
    tmp_path: Path, parameter: str, valid: bool
) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        f'''from dataclasses import dataclass, field

@dataclass
class Base:
    timeout: int

@dataclass
class Client(Base):
    """Connect to a service.

    Args:
        {parameter}: Limit the wait in seconds.
    """

    state: int = field(init=False)
''',
        encoding="utf-8",
    )
    result = _run_doclint(path)
    assert result.returncode == (0 if valid else 1), result.stderr
    if not valid:
        assert f"constructor parameter {parameter!r} does not exist" in result.stderr


@pytest.mark.parametrize(
    ("class_header", "valid"),
    [("class Client(BaseModel):", True), ("@dataclass\nclass Client:", False)],
)
def test_doclint_distinguishes_unknown_and_empty_constructors(
    tmp_path: Path, class_header: str, valid: bool
) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        f'''from dataclasses import dataclass, field
from pydantic import BaseModel

{class_header}
    """Store a value.

    Args:
        value: The value to store.
    """

    value: int{" = field(init=False)" if not valid else ""}
''',
        encoding="utf-8",
    )
    result = _run_doclint(path)
    assert result.returncode == (0 if valid else 1), result.stderr
    if not valid:
        assert "constructor parameter 'value' does not exist" in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        '''def f(timeout: int, retries: int, limit: int) -> int:
    """Return the timeout.

    Args:
        timeout: The input in seconds.
        timeout: The input in minutes.
    """
    return timeout
''',
        '''class Client:
    """Create a client.

    Args:
        timeout: The input in seconds.
        timeout: The input in minutes.
    """

    def __init__(self, timeout: int, retries: int, limit: int):
        pass
''',
    ],
)
def test_repeated_parameter_is_not_selective_documentation(
    tmp_path: Path, source: str
) -> None:
    path = tmp_path / "example.py"
    path.write_text(source, encoding="utf-8")
    result = _run_doclint(path)
    assert result.returncode == 1
    assert "repeated Args entry 'timeout'" in result.stderr


def test_repeated_parameter_sections_fail(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        '''def f(timeout: int) -> int:
    """Return the timeout.

    Args:
        deadline: The obsolete parameter in seconds.

    Args:
        timeout: The input in seconds.
    """
    return timeout
''',
        encoding="utf-8",
    )
    result = _run_doclint(path)
    assert result.returncode == 1
    assert "repeated Args section" in result.stderr


@pytest.mark.parametrize(
    "opening",
    ["````text", '```` {.text title="Use `timeout`"}', "~~~text\n\n    ````text"],
)
def test_parameter_heading_inside_example_is_not_a_section(
    tmp_path: Path, opening: str
) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        f'''def f(timeout: int) -> int:
    """Return the timeout.

    {opening}
    Args:
        deadline: Part of the example.
    ```
    ````

    Args:
        timeout: The input in seconds.
    """
    return timeout
''',
        encoding="utf-8",
    )
    result = _run_doclint(path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("prefix", ["```timeout``` is measured in seconds.", "```text"])
def test_unpaired_fence_does_not_hide_duplicate_args(
    tmp_path: Path, prefix: str
) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        f'''def f(timeout: int, retries: int, limit: int) -> int:
    """Return the timeout.

    {prefix}

    Args:
        timeout: The input in seconds.
        timeout: The input in minutes.
    """
    return timeout
''',
        encoding="utf-8",
    )
    result = _run_doclint(path)
    assert result.returncode == 1
    assert "repeated Args entry 'timeout'" in result.stderr


@pytest.mark.parametrize(
    ("decorator", "violation"),
    [
        ("@dataclass", ""),
        ("@dataclass(init=False)", "document constructor arguments on __new__"),
    ],
)
def test_class_args_account_for_generated_init(
    tmp_path: Path, decorator: str, violation: str
) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        f'''from dataclasses import dataclass

{decorator}
class Reader:
    """Read a file.

    Args:
        timeout: Limit the wait in seconds.
    """

    timeout: int

    def __new__(cls, timeout: int) -> Reader:
        """Allocate a reader."""
        return super().__new__(cls)
''',
        encoding="utf-8",
    )
    result = _run_doclint(path)
    assert result.returncode == (1 if violation else 0), result.stderr
    assert violation in result.stderr


@pytest.mark.parametrize("gate", ["comments", "docstrings"])
def test_python_file_walk_does_not_skip_unreadable_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    gate: str,
) -> None:
    error = PermissionError("unreadable directory")

    def walk(path: Path, *, on_error: Callable[[OSError], None]) -> None:
        assert path == tmp_path
        on_error(error)

    monkeypatch.setattr(Path, "walk", walk)
    monkeypatch.setattr(sys, "argv", [str(_TOOL), gate, str(tmp_path)])
    assert main() == 1
    assert "unreadable directory" in capsys.readouterr().err


def test_tracker_gate_ignores_executable_strings() -> None:
    source = '''"""PL-123."""
LINK = "https://github.com/punt-labs/lux/issues/9"

async def f() -> str:
    """Read the value (lux-ab12)."""
    # See https://linear.app/punt-labs/issue/pl-100/example.
    return "PR #42"

# PL-PL-2 is a lint rule, not a tracker reference.
# lux-cli and PL-123-example are not tracker tokens.
'''
    findings = tracker_references(source, "example.py")
    assert [line.split(":")[:2] for line in findings] == [
        ["example.py", "1"],
        ["example.py", "5"],
        ["example.py", "6"],
    ]


def test_tracker_gate_checks_attribute_docstrings() -> None:
    source = '''type ClientId = str
"""Use a client ID (PL-123)."""
LINK = "PR #9"

class Client:
    state: str = ""
    """Read its state (lux-ab12)."""

    def __init__(self):
        self.ready = False
        """Record if it is ready (PR #42)."""
'''
    assert [
        line.split(":")[:2] for line in tracker_references(source, "example.py")
    ] == [["example.py", "2"], ["example.py", "7"], ["example.py", "11"]]


def test_public_docstrings_follow_reexports_and_mcp_registration(
    tmp_path: Path,
) -> None:
    package = tmp_path / "example"
    package.mkdir()
    (package / "__init__.py").write_text(
        'from ._impl import Client\n__all__ = ["Client"]\n', encoding="utf-8"
    )
    (package / "_impl.py").write_text(
        '''class Client:
    """Connect to the service."""

    def request(self):
        pass

    def _helper(self):
        pass


class Internal:
    pass


@mcp.tool(name="inspect")
def _inspect():
    pass
''',
        encoding="utf-8",
    )
    findings = public_doc_findings(tmp_path, ("example",))
    assert findings == [
        f"Missing public docstring: {package / '_impl.py'}:16: _inspect",
        "Missing public docstring: example._impl.Client.request",
    ]


def test_missing_api_directive_is_detected() -> None:
    header = (
        b"# Sphinx inventory version 2\n"
        b"# Project: Lux\n"
        b"# Version: \n"
        b"# The remainder of this file is compressed using zlib.\n"
    )
    expected = missing_api_symbols(header + zlib.compress(b""))
    assert "punt_lux.LuxClient" in expected
    entries = "".join(f"{name} py:function 1 index.html#\x24 -\n" for name in expected)
    assert not missing_api_symbols(header + zlib.compress(entries.encode()))
