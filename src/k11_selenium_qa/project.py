"""What kind of test project this is: Python (pytest) or Java (Maven / Gradle)."""

from __future__ import annotations

import os
from pathlib import Path


def language(root: Path) -> str:
    """QA_MCP_LANGUAGE (python|java), else java when there is a pom.xml or build.gradle, else python."""
    forced = os.environ.get("QA_MCP_LANGUAGE", "").lower()
    if forced in ("python", "java"):
        return forced
    root = Path(root)
    if any((root / f).is_file() for f in ("pom.xml", "build.gradle", "build.gradle.kts")):
        return "java"
    return "python"


def java_framework(root: Path) -> str:
    """testng when the build mentions it, else junit5."""
    for f in ("pom.xml", "build.gradle", "build.gradle.kts"):
        p = Path(root) / f
        if p.is_file() and "testng" in p.read_text("utf8", errors="replace").lower():
            return "testng"
    return "junit5"


JAVA_TEST_ROOTS = ("src/test/java", "src/main/java")
