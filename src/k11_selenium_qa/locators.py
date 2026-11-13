"""Selenium locators: parse, render, count and infer, without ever eval'ing code.

A locator is a (by, value) pair using Selenium's own strategy names
("id", "css selector", "xpath", ...). Strings from tests or from the model are
parsed with a strict pattern and ``ast.literal_eval`` for the string literal.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

# Selenium By constant name -> strategy string
BY = {
    "ID": "id",
    "NAME": "name",
    "CSS_SELECTOR": "css selector",
    "XPATH": "xpath",
    "LINK_TEXT": "link text",
    "PARTIAL_LINK_TEXT": "partial link text",
    "CLASS_NAME": "class name",
    "TAG_NAME": "tag name",
}
BY_CONST = {v: k for k, v in BY.items()}


@dataclass(frozen=True)
class Loc:
    by: str  # strategy string, e.g. "id"
    value: str

    def normalized(self) -> "Loc":
        """Map Selenium's internal CSS forms back to the strategy the test used."""
        if self.by == "css selector":
            m = re.fullmatch(r'\[id="((?:[^"\\]|\\.)*)"\]', self.value)
            if m:
                return Loc("id", _css_unescape(m.group(1)))
            m = re.fullmatch(r'\[name="((?:[^"\\]|\\.)*)"\]', self.value)
            if m:
                return Loc("name", _css_unescape(m.group(1)))
        return self


def _css_unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def pyq(s: str) -> str:
    """Python string literal, preferring double quotes."""
    if '"' in s and "'" not in s:
        return "'" + s.replace("\\", "\\\\") + "'"
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(loc: Loc) -> str:
    return f"(By.{BY_CONST[loc.by]}, {pyq(loc.value)})"


_STR = r"""(?:[rRuU]?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'))"""
_PATTERNS = [
    # (By.ID, "x")   By.ID, "x"   find_element(By.ID, "x")
    re.compile(rf"^(?:[\w.]*\(\s*)*\(?\s*By\.([A-Z_]+)\s*,\s*({_STR})[\s)]*$", re.S),
    # find_element("id", "x")   ("css selector", "x")
    re.compile(rf"^(?:[\w.]*\(\s*)*\(?\s*({_STR})\s*,\s*({_STR})[\s)]*$", re.S),
]


def parse_locator(text: str) -> Loc | None:
    """Parse one Selenium locator expression. Returns None for anything else."""
    s = (text or "").strip().rstrip(";")
    m = re.fullmatch(r'\{\s*"method"\s*:\s*"([a-z ]+)"\s*,\s*"selector"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', s)
    if m:  # WebDriver error payload
        return Loc(m.group(1), _css_unescape(m.group(2))).normalized() if m.group(1) in BY_CONST else None
    m = _PATTERNS[0].match(s)
    if m and m.group(1) in BY:
        return _mk(BY[m.group(1)], m.group(2))
    m = _PATTERNS[1].match(s)
    if m:
        try:
            by = ast.literal_eval(m.group(1))
        except (ValueError, SyntaxError):
            return None
        if by in BY_CONST:
            return _mk(by, m.group(2))
    return None


def _mk(by: str, literal: str) -> Loc | None:
    try:
        value = ast.literal_eval(literal)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(value, str) or not value:
        return None
    return Loc(by, value).normalized()


def count_matches(driver, loc: Loc) -> int:
    """Number of elements matched on the live page; invalid selectors count as 0."""
    try:
        return len(driver.find_elements(loc.by, loc.value))
    except Exception:  # noqa: BLE001 - invalid selector etc.
        return 0


# Suggestion order: most stable first.
PRIORITY = {"testid": 0, "id": 1, "name": 2, "link": 3, "aria": 4, "text": 5, "placeholder": 6}


def css_attr(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def xpath_lit(value: str) -> str | None:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    return None


_UNSTABLE_ID = re.compile(r"\d{3,}|[:]|^[a-f0-9]{8,}$|^(ember|react|mui|radix|headlessui)", re.I)


def stable_id(value: str | None) -> bool:
    return bool(value) and re.fullmatch(r"[A-Za-z][\w-]*", value) is not None and not _UNSTABLE_ID.search(value)


def implied_fingerprint(loc: Loc) -> dict[str, str]:
    """Best-effort partial fingerprint implied by a locator, used when no baseline exists."""
    v = loc.value
    out: dict[str, str] = {}
    if loc.by == "id":
        out["id"] = v
    elif loc.by == "name":
        out["nameAttr"] = v
    elif loc.by == "link text":
        out.update(role="link", name=v)
    elif loc.by == "partial link text":
        out.update(role="link", name=v)
    elif loc.by == "class name":
        out["classes"] = v
    elif loc.by == "tag name":
        out["tag"] = v.lower()
    elif loc.by == "css selector":
        if m := re.search(r"#([\w-]+)", v):
            out["id"] = m.group(1)
        if m := re.match(r"([a-z][a-z0-9]*)", v, re.I):
            out["tag"] = m.group(1).lower()
        if m := re.search(r"\[(?:data-testid|data-test|data-qa)\s*=\s*[\"']?([^\"'\]]+)", v):
            out["testId"] = m.group(1)
        if m := re.search(r"\[name\s*=\s*[\"']?([^\"'\]]+)", v):
            out["nameAttr"] = m.group(1)
        if m := re.search(r"\[aria-label\s*=\s*[\"']?([^\"'\]]+)", v):
            out["name"] = m.group(1)
        if m := re.search(r"\[placeholder\s*=\s*[\"']?([^\"'\]]+)", v):
            out["placeholder"] = m.group(1)
        classes = re.findall(r"\.([A-Za-z_][\w-]*)", v)
        if classes:
            out["classes"] = " ".join(classes)
    elif loc.by == "xpath":
        if m := re.match(r"^\.?//?([a-z][a-z0-9]*)", v, re.I):
            out["tag"] = m.group(1).lower()
        for attr, key in (("id", "id"), ("name", "nameAttr"), ("data-testid", "testId"), ("placeholder", "placeholder"),
                          ("aria-label", "name"), ("class", "classes")):
            if m := re.search(rf"@{re.escape(attr)}\s*=\s*[\"']([^\"']+)[\"']", v):
                out[key] = m.group(1)
        if m := re.search(r"(?:normalize-space\(\s*(?:\.|text\(\))?\s*\)|text\(\)|\.)\s*=\s*[\"']([^\"']+)[\"']", v):
            out.setdefault("name", m.group(1))
        elif m := re.search(r"contains\(\s*(?:text\(\)|\.|normalize-space\([^)]*\))\s*,\s*[\"']([^\"']+)[\"']\s*\)", v):
            out.setdefault("name", m.group(1))
    return out
