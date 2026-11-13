"""Rewrite a Selenium locator in Python source, using the tokenizer (comments are skipped).

Finds ``By.<STRATEGY>, "<value>"`` wherever it appears: ``find_element(...)``
calls, expected conditions, and Page Object constants such as
``LOGIN = (By.ID, "login-btn")``. Only the strategy and the string change.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path

from .locators import BY, BY_CONST, Loc, pyq

SKIP_DIRS = {".venv", "venv", "env", ".git", "node_modules", "__pycache__", ".qa-mcp", ".tox", ".nox",
             "site-packages", "build", "dist", ".pytest_cache", ".mypy_cache"}


@dataclass
class Replacement:
    file: str
    line: int
    before: str
    after: str


def _find(source: str, target: Loc) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Spans (start, end) of `By.X, "v"` occurrences that equal the target locator."""
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(source).readline)
                if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    spans = []
    for i in range(len(toks) - 4):
        a, dot, const, comma, s = toks[i:i + 5]
        if not (a.string == "By" and dot.string == "." and const.type == tokenize.NAME and const.string in BY
                and comma.string == "," and s.type == tokenize.STRING):
            continue
        if i > 0 and toks[i - 1].string == ".":  # e.g. webdriver.common.by.By is fine, x.By is not ours to judge
            pass
        try:
            value = ast.literal_eval(s.string)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(value, str):
            continue
        if Loc(BY[const.string], value).normalized() == target.normalized():
            spans.append((const.start, s.end))
    return spans


def _offset(lines: list[str], pos: tuple[int, int]) -> int:
    row, col = pos
    return sum(len(l) for l in lines[: row - 1]) + col


def replace_locator(source: str, broken: Loc, healed: Loc, file: str = "") -> tuple[str, list[Replacement]]:
    spans = _find(source, broken)
    if not spans:
        return source, []
    lines = source.splitlines(keepends=True)
    new = f"{BY_CONST[healed.by]}, {pyq(healed.value)}"
    out = source
    reps = []
    for start, end in reversed(spans):
        a, b = _offset(lines, start), _offset(lines, end)
        reps.append(Replacement(file, start[0], "By." + out[a:b], "By." + new))
        out = out[:a] + new + out[b:]
    reps.reverse()
    return out, reps


def python_files(root: Path):
    root = Path(root)
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part.startswith(".tmp") for part in rel.parts[:-1]):
            continue
        yield p


def locate_in_project(root: Path, broken: Loc, prefer: Path | None = None) -> list[Path]:
    """Files under the project that contain the broken locator (the test file first)."""
    found = [p for p in python_files(root) if _find(p.read_text("utf8", errors="replace"), broken)]
    if prefer:
        found.sort(key=lambda p: 0 if p.resolve() == Path(prefer).resolve() else 1)
    return found
