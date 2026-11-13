"""User story parsing and pytest + Selenium scaffolding.

Accepts the formats teams actually write:
  As a <role>, I want <goal> so that <benefit>.
  Scenario: ... / Given ... When ... Then ... And ... But ...
  Acceptance criteria as bullets or numbered lines (each becomes a scenario).
"""

from __future__ import annotations

import re
from typing import Any

STEP_RE = re.compile(r"^(given|when|then|and|but)\b[:\s]*(.*)$", re.I)


def parse_story(raw: str) -> dict[str, Any]:
    text = raw.replace("\r", "")
    story: dict[str, Any] = {"title": "", "scenarios": []}
    m = re.search(r"as an?\s+(.+?),?\s+i (?:want|need|would like)(?: to)?\s+(.+?)(?:,?\s+so that\s+(.+?))?(?:\.|\n|$)", text, re.I)
    if m:
        story["role"], story["goal"] = m.group(1).strip(), m.group(2).strip()
        if m.group(3):
            story["benefit"] = m.group(3).strip()
    t = re.search(r"^(?:title|story|feature)\s*:\s*(.+)$", text, re.I | re.M)
    first = next((ln for ln in text.split("\n") if ln.strip()), "User story")
    title = (t.group(1) if t else story.get("goal") or first).strip()
    story["title"] = title[:1].upper() + title[1:]

    current = None
    bullets: list[str] = []
    for line in (ln.strip() for ln in text.split("\n")):
        if not line:
            continue
        sc = re.match(r"^scenario(?: outline)?\s*:\s*(.+)$", line, re.I)
        if sc:
            current = {"name": sc.group(1).strip(), "steps": []}
            story["scenarios"].append(current)
            continue
        st = STEP_RE.match(re.sub(r"^[-*•]\s*", "", line))
        if st:
            if current is None:
                current = {"name": f"Scenario {len(story['scenarios']) + 1}", "steps": []}
                story["scenarios"].append(current)
            current["steps"].append({"keyword": st.group(1).capitalize(), "text": st.group(2).strip()})
            continue
        b = re.match(r"^(?:[-*•]|\d+[.)]|ac\s*\d+\s*[:.-])\s*(.+)$", line, re.I)
        if b and not re.match(r"^as an?\s", b.group(1), re.I):
            bullets.append(b.group(1).strip())
    if not story["scenarios"]:
        story["scenarios"] = [{"name": b, "steps": [{"keyword": "Check", "text": b}]} for b in bullets]
    if not story["scenarios"] and story.get("goal"):
        story["scenarios"] = [{"name": story["goal"], "steps": [{"keyword": "Check", "text": story["goal"]}]}]
    return story


def _ident(s: str, prefix: str = "") -> str:
    words = re.findall(r"[A-Za-z0-9]+", s.lower())
    name = "_".join(words)[:60].strip("_") or "scenario"
    return prefix + name


def _cls(s: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", s)
    return "Test" + "".join(w[:1].upper() + w[1:] for w in words)[:50]


def _lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def scaffold_test(story: dict[str, Any], url: str | None = None) -> str:
    """pytest skeleton: one test per scenario, a comment per step, TODOs to fill."""
    L = [
        "from selenium.webdriver.common.by import By",
        "from selenium.webdriver.support import expected_conditions as EC",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "",
    ]
    if url:
        L += [f"START_URL = {_lit(url)}", ""]
    L += ["", f"class {_cls(story['title'])}:"]
    if story.get("role") or story.get("goal"):
        who = f"a {story['role']}" if story.get("role") else "a user"
        so = f" so that {story['benefit']}" if story.get("benefit") else ""
        L.append(f'    """As {who}, I want {story.get("goal", "…")}{so}."""')
        L.append("")
    seen: set[str] = set()
    for i, sc in enumerate(story["scenarios"]):
        name = _ident(sc["name"], "test_")
        while name in seen:
            name += "_2"
        seen.add(name)
        L.append(f"    def {name}(self, driver):")
        L.append(f'        """{sc["name"].replace(chr(34) * 3, "")}"""')
        L.append("        wait = WebDriverWait(driver, 10)")
        if url:
            L.append("        driver.get(START_URL)")
        for st in sc["steps"]:
            L.append(f"        # {st['keyword']} {st['text']}")
            if st["keyword"] in ("Then", "Check"):
                L.append("        # TODO: assert with an explicit wait, e.g. "
                         "assert wait.until(EC.visibility_of_element_located((By.ID, \"...\"))).text == \"...\"")
            else:
                L.append("        # TODO: action using a verified locator from explore_page")
        if i < len(story["scenarios"]) - 1:
            L.append("")
    L.append("")
    return "\n".join(L)


def _jlit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _camel(s: str, upper: bool = False) -> str:
    words = re.findall(r"[A-Za-z0-9]+", s)
    name = "".join(w[:1].upper() + w[1:].lower() for w in words)[:60] or "Scenario"
    if name[0].isdigit():
        name = "S" + name
    return name if upper else name[:1].lower() + name[1:]


def scaffold_java(story: dict[str, Any], url: str | None = None, package: str | None = None,
                  framework: str = "junit5", class_name: str | None = None) -> str:
    """JUnit 5 or TestNG skeleton: one test method per scenario, a comment per step, TODOs to fill."""
    cls = class_name or (_camel(story["title"], upper=True) + "Test")
    testng = framework == "testng"
    L = [f"package {package};", ""] if package else []
    L += [
        "import java.time.Duration;",
        "",
        "import org.openqa.selenium.By;",
        "import org.openqa.selenium.WebDriver;",
        "import org.openqa.selenium.chrome.ChromeDriver;",
        "import org.openqa.selenium.chrome.ChromeOptions;",
        "import org.openqa.selenium.support.ui.ExpectedConditions;",
        "import org.openqa.selenium.support.ui.WebDriverWait;",
    ]
    if testng:
        L += ["import org.testng.annotations.AfterMethod;", "import org.testng.annotations.BeforeMethod;",
              "import org.testng.annotations.Test;", "", "import static org.testng.Assert.*;"]
    else:
        L += ["import org.junit.jupiter.api.AfterEach;", "import org.junit.jupiter.api.BeforeEach;",
              "import org.junit.jupiter.api.DisplayName;", "import org.junit.jupiter.api.Test;", "",
              "import static org.junit.jupiter.api.Assertions.*;"]
    L.append("")
    if story.get("role") or story.get("goal"):
        who = f"a {story['role']}" if story.get("role") else "a user"
        so = f" so that {story['benefit']}" if story.get("benefit") else ""
        L.append(f"/** As {who}, I want {story.get('goal', '…')}{so}. */")
    L.append(f"{'public ' if testng else ''}class {cls} {{")
    if url:
        L.append(f"    private static final String START_URL = {_jlit(url)};")
    L += [
        "    private WebDriver driver;",
        "    private WebDriverWait wait;",
        "",
        f"    @{'BeforeMethod' if testng else 'BeforeEach'}",
        f"    {'public ' if testng else ''}void setUp() {{",
        "        ChromeOptions options = new ChromeOptions();",
        "        options.addArguments(\"--headless=new\", \"--window-size=1280,900\");",
        "        driver = new ChromeDriver(options);",
        "        wait = new WebDriverWait(driver, Duration.ofSeconds(10));",
        "    }",
        "",
        f"    @{'AfterMethod' if testng else 'AfterEach'}",
        f"    {'public ' if testng else ''}void tearDown() {{",
        "        if (driver != null) driver.quit();",
        "    }",
    ]
    seen: set[str] = set()
    for sc in story["scenarios"]:
        name = _camel(sc["name"])
        while name in seen:
            name += "2"
        seen.add(name)
        L.append("")
        if testng:
            L.append(f"    @Test(description = {_jlit(sc['name'])})")
        else:
            L += ["    @Test", f"    @DisplayName({_jlit(sc['name'])})"]
        L.append(f"    {'public ' if testng else ''}void {name}() {{")
        if url:
            L.append("        driver.get(START_URL);")
        for st in sc["steps"]:
            L.append(f"        // {st['keyword']} {st['text']}")
            if st["keyword"] in ("Then", "Check"):
                L.append("        // TODO: assert with an explicit wait, e.g. "
                         "assertEquals(\"...\", wait.until(ExpectedConditions.visibilityOfElementLocated(By.id(\"...\"))).getText());")
            else:
                L.append("        // TODO: action using a verified locator from explore_page")
        L.append("    }")
    L += ["}", ""]
    return "\n".join(L)


CONFTEST = '''import os

import pytest
from selenium import webdriver


@pytest.fixture
def driver():
    """Headless Chrome. Set HEADED=1 to watch the browser."""
    opts = webdriver.ChromeOptions()
    if os.environ.get("HEADED") != "1":
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    drv = webdriver.Chrome(options=opts)
    yield drv
    drv.quit()
'''
