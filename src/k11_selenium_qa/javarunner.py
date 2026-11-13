"""Run a Java Selenium suite with Maven or Gradle and read the JUnit XML reports.

No shell is used; test filters are validated against a strict pattern. The failing
locator comes from Selenium's own exception text (By.toString() in timeouts, the
WebDriver payload in NoSuchElementException), and the line from the stack trace.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .locators import parse_locator, render
from .project import JAVA_TEST_ROOTS

FILTER_RE = re.compile(r"^[\w.$*]+(?:#[\w*]+(?:\+[\w*]+)*)?$")
LOCATOR_ERRORS = ("NoSuchElementException", "TimeoutException")


def build_tool(root: Path) -> tuple[str, list[str], Path] | None:
    """(kind, base command, report dir)."""
    win = os.name == "nt"
    if (root / "pom.xml").is_file():
        wrapper = root / ("mvnw.cmd" if win else "mvnw")
        exe = str(wrapper) if wrapper.is_file() else shutil.which("mvn")
        return ("maven", [exe, "-B", "test", "-Dsurefire.failIfNoSpecifiedTests=false",
                          "-DtrimStackTrace=false"], root / "target" / "surefire-reports") if exe else None
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        wrapper = root / ("gradlew.bat" if win else "gradlew")
        exe = str(wrapper) if wrapper.is_file() else shutil.which("gradle")
        return ("gradle", [exe, "test", "--continue"], root / "build" / "test-results" / "test") if exe else None
    return None


def class_file(root: Path, cls: str) -> Path | None:
    outer = cls.split("$")[0]
    rel = outer.replace(".", "/") + ".java"
    for base in JAVA_TEST_ROOTS:
        p = root / base / rel
        if p.is_file():
            return p
    name = outer.split(".")[-1] + ".java"
    return next((p for p in root.rglob(name) if "target" not in p.parts and "build" not in p.parts), None)


_FRAME = re.compile(r"at ([\w.$]+)\.([\w$<>]+)\((\w+\.java):(\d+)\)")
_TOSTRING = re.compile(r"\bBy\.(id|name|cssSelector|xpath|linkText|partialLinkText|className|tagName): (.+?)"
                       r"(?: to be (?:clickable|visible|present)| \(tried for |\)?\s*$|\n)")
_PAYLOAD = re.compile(r'\{"method":"([a-z ]+)","selector":"((?:[^"\\]|\\.)*)"\}')


def failing_locator(message: str) -> str | None:
    m = _TOSTRING.search(message)
    if m:
        loc = parse_locator(f"By.{m.group(1)}: {m.group(2)}")
        if loc:
            return render(loc)
    m = _PAYLOAD.search(message)
    if m:
        loc = parse_locator(m.group(0))
        if loc:
            return render(loc)
    return None


def parse_reports(root: Path, report_dir: Path) -> list[dict[str, Any]]:
    tests = []
    for f in sorted(report_dir.glob("TEST-*.xml")):
        try:
            suite = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        for tc in suite.iter("testcase"):
            cls, name = tc.get("classname", ""), tc.get("name", "").split("(")[0]
            file = class_file(root, cls)
            item: dict[str, Any] = {
                "test": f"{cls}#{name}",
                "name": name,
                "file": file.relative_to(root).as_posix() if file else cls,
                "filePath": str(file) if file else None,
                "status": "passed",
                "duration": float(tc.get("time") or 0),
            }
            bad = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
            if tc.find("skipped") is not None:
                item["status"] = "skipped"
            elif bad is not None:
                item["status"] = "failed"
                etype = (bad.get("type") or "").split(".")[-1]
                message = bad.get("message") or ""
                body = bad.text or ""
                item["errorType"] = etype
                item["error"] = f"{etype}: {message.splitlines()[0] if message else ''}".strip().rstrip(":")
                if etype in LOCATOR_ERRORS:
                    loc = failing_locator(message + "\n" + body)
                    if loc:
                        item["failingLocator"] = loc
                # First frame in the project's own sources (Page Object or test), and the test's own line.
                for fcls, _meth, fname, line in _FRAME.findall(body):
                    if fcls.startswith(("org.openqa.", "java.", "jdk.", "sun.", "org.junit.", "org.testng.",
                                        "org.apache.maven.", "org.gradle.")):
                        continue
                    src = class_file(root, fcls)
                    if src:
                        item.setdefault("locatorFile", src.relative_to(root).as_posix())
                        item.setdefault("locatorLine", int(line))
                    if fcls == cls:
                        item["errorLine"] = int(line)
                        break
            tests.append(item)
    return tests


def run_java_tests(root: Path, targets: list[str] | None = None, timeout_s: int = 900,
                   extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    tool = build_tool(root)
    if not tool:
        return {"error": "No Maven or Gradle build found (pom.xml / build.gradle), or mvn/gradle is not on PATH.", "tests": []}
    kind, cmd, report_dir = tool
    for t in targets or []:
        if not FILTER_RE.match(t):
            raise ValueError(f"Unsupported test filter: {t}. Use Class, pkg.Class or Class#method.")
    if targets:
        if kind == "maven":
            by_class: dict[str, list[str]] = {}
            for t in targets:
                c, _, m = t.partition("#")
                by_class.setdefault(c, []).extend(m.split("+") if m else [])
            cmd = cmd + ["-Dtest=" + ",".join(f"{c}#{'+'.join(ms)}" if ms else c for c, ms in by_class.items())]
        else:
            for t in targets:
                cmd = cmd + ["--tests", t.replace("#", ".")]
    shutil.rmtree(report_dir, ignore_errors=True)
    env = {**os.environ, **(extra_env or {})}
    try:
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"error": f"Tests timed out after {timeout_s}s", "tests": []}
    tests = parse_reports(root, report_dir) if report_dir.is_dir() else []
    if not tests and proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-20:]
        return {"error": f"{kind} failed before any test ran (compilation error?)", "exitCode": proc.returncode,
                "output": "\n".join(tail), "tests": []}
    counts = {s: sum(1 for t in tests if t["status"] == s) for s in ("passed", "failed", "error", "skipped")}
    return {**counts, "total": len(tests), "exitCode": proc.returncode, "runner": kind, "tests": tests}
