"""Rewrite a Selenium locator in source code, without touching anything else.

Python: uses the tokenizer to find ``By.<STRATEGY>, "<value>"`` wherever it appears
(``find_element(...)`` calls, expected conditions, Page Object constants such as
``LOGIN = (By.ID, "login-btn")``). Comments are skipped.

Java: finds ``By.id("...")``-style calls and ``@FindBy(...)`` annotations (including
``how = How.ID, using = "..."``), with comments blanked out first.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

from .locators import (BY, BY_CONST, FINDBY_KEY_REV, JAVA_BY, JSTR, Loc, java_unescape, javaq,
                       parse_findby_args, pyq, render)

SKIP_DIRS = {".venv", "venv", "env", ".git", "node_modules", "__pycache__", ".qa-mcp", ".tox", ".nox",
             "site-packages", "build", "dist", ".pytest_cache", ".mypy_cache", "target", ".gradle", ".idea", "out"}


@dataclass
class Replacement:
    file: str
    line: int
    before: str
    after: str


# ---- Python -----------------------------------------------------------------

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
        try:
            value = ast.literal_eval(s.string)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, str) and Loc(BY[const.string], value).normalized() == target.normalized():
            spans.append((const.start, s.end))
    return spans


def _offset(lines: list[str], pos: tuple[int, int]) -> int:
    row, col = pos
    return sum(len(line) for line in lines[: row - 1]) + col


def replace_locator(source: str, broken: Loc, healed: Loc, file: str = "") -> tuple[str, list[Replacement]]:
    if file.endswith(".java"):
        return replace_java(source, broken, healed, file)
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


# ---- Java -------------------------------------------------------------------

NL, BS, DQ, SQ = "\n", "\\", '"', "'"


def _skip_literal(src: str, i: int, quote: str) -> int:
    """Index just past the literal starting at src[i] (a quote)."""
    j = i + 1
    while j < len(src) and src[j] != quote and src[j] != NL:
        j += 2 if src[j] == BS else 1
    return j + 1


def _mask_java(src: str) -> str:
    """Copy of the source with comments blanked (same length, newlines kept); literals kept."""
    out, i, n = list(src), 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find(NL, i)
            j = n if j < 0 else j
            out[i:j] = [" "] * (j - i)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out[i:j] = [ch if ch == NL else " " for ch in src[i:j]]
            i = j
        elif src.startswith(DQ * 3, i):  # text block
            j = src.find(DQ * 3, i + 3)
            i = n if j < 0 else j + 3
        elif src[i] in (DQ, SQ):
            i = _skip_literal(src, i, src[i])
        else:
            i += 1
    return "".join(out)


def _close_paren(text: str, open_idx: int) -> int:
    """Index of the parenthesis closing text[open_idx], skipping string literals."""
    depth, i = 0, open_idx
    while i < len(text):
        c = text[i]
        if c in (DQ, SQ):
            i = _skip_literal(text, i, c)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_JCALL = re.compile(rf"\bBy\s*\.\s*(\w+)\s*\(\s*({JSTR})\s*\)")
_JFINDBY = re.compile(r"@FindBy\s*\(")


def _find_java(src: str, target: Loc) -> list[tuple[int, int, str]]:
    """(start, end, kind) spans of By.x("v") calls and @FindBy(...) annotations equal to target."""
    masked = _mask_java(src)
    want = target.normalized()
    spans = []
    for m in _JCALL.finditer(masked):
        if m.group(1) in JAVA_BY:
            value = java_unescape(m.group(2))
            if value and Loc(JAVA_BY[m.group(1)], value).normalized() == want:
                spans.append((m.start(), m.end(), "call"))
    for m in _JFINDBY.finditer(masked):
        close = _close_paren(masked, m.end() - 1)
        if close > 0 and parse_findby_args(masked[m.end():close]) == want:
            spans.append((m.start(), close + 1, "findby"))
    return sorted(spans)


def render_java_findby(loc: Loc) -> str:
    return f"@FindBy({FINDBY_KEY_REV[loc.by]} = {javaq(loc.value)})"


def replace_java(source: str, broken: Loc, healed: Loc, file: str = "") -> tuple[str, list[Replacement]]:
    out, reps = source, []
    for start, end, kind in reversed(_find_java(source, broken)):
        new = render(healed, "java") if kind == "call" else render_java_findby(healed)
        reps.append(Replacement(file, source.count(NL, 0, start) + 1, source[start:end], new))
        out = out[:start] + new + out[end:]
    reps.reverse()
    return out, reps


# ---- Project search ---------------------------------------------------------

def source_files(root: Path):
    root = Path(root)
    for pattern in ("*.py", "*.java"):
        for p in root.rglob(pattern):
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS or part.startswith(".tmp") for part in rel.parts[:-1]):
                continue
            yield p


def contains_locator(path: Path, broken: Loc) -> bool:
    text = path.read_text("utf8", errors="replace")
    return bool(_find_java(text, broken) if path.suffix == ".java" else _find(text, broken))


def locate_in_project(root: Path, broken: Loc, prefer: Path | None = None) -> list[Path]:
    """Files under the project that contain the broken locator (the failing test's file first)."""
    found = [p for p in source_files(root) if contains_locator(p, broken)]
    if prefer:
        found.sort(key=lambda p: 0 if p.resolve() == Path(prefer).resolve() else 1)
    return found
