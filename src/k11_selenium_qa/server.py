"""MCP server: Selenium test generation and self-healing locators."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .browser import open_page
from .heal import heal
from .locators import count_matches, parse_locator, render
from .runner import run_tests as _run_tests
from .session import MAX_STEPS, capture_storage_state
from .snapshot import explore, fingerprint_of
from .store import BaselineStore
from .story import CONFTEST, parse_story, scaffold_test
from .version import VERSION


def project_root() -> Path:
    return Path(os.environ.get("QA_MCP_ROOT") or os.getcwd()).resolve()


class Step(BaseModel):
    action: Literal["goto", "click", "fill", "press", "select", "check", "uncheck", "wait_for"]
    locator: Optional[str] = Field(None, description='Selenium locator, e.g. (By.ID, "email")')
    value: Optional[str] = Field(None, description="For fill/press/select. Use ${ENV:NAME} for secrets.")
    url: Optional[str] = Field(None, description="For goto; absolute or relative to the start URL")


class Session(BaseModel):
    storage_state: Optional[str] = Field(None, description="Saved login inside the project, e.g. .qa-mcp/auth/default.json")
    steps: Optional[list[Step]] = Field(None, max_length=MAX_STEPS, description="Steps to run after the page loads")


SessionArg = Annotated[Optional[Session], Field(description="Optional: reach a page behind a login or several steps into a flow")]


def _sess(session: Optional[Session]) -> dict[str, Any] | None:
    return session.model_dump(exclude_none=True) if session else None


def _ensure_gitignored(root: Path, entry: str) -> None:
    gi = root / ".gitignore"
    text = gi.read_text("utf8") if gi.is_file() else ""
    if entry not in text.splitlines():
        gi.write_text(text + ("" if text.endswith("\n") or not text else "\n") + entry + "\n", "utf8")


def create_server() -> FastMCP:
    mcp = FastMCP(
        "k11-selenium-qa",
        instructions=(
            "Selenium QA tools. Get locators from explore_page instead of guessing; they are verified to match "
            "exactly one element. Write pytest tests with write_test, run them with run_tests, and for locator "
            "failures call heal_locator. Never put passwords in tool arguments: use ${ENV:NAME}."
        ),
    )

    @mcp.tool(title="Explore page")
    def explore_page(url: str, only_interactive: bool = True, max_elements: int = 60, session: SessionArg = None) -> dict:
        """Open a URL and list elements with Selenium locators verified to match exactly one element, most stable first."""
        with open_page(url, project_root(), _sess(session)) as v:
            els = explore(v.driver, max(1, min(max_elements, 200)), only_interactive)
            return {"url": v.final_url, "title": v.driver.title, "stepsRun": v.steps, "elements": els}

    @mcp.tool(title="Check locator")
    def check_locator(url: str, locator: str, session: SessionArg = None) -> dict:
        """Count what a Selenium locator matches on a page (1 = good) and whether it is visible."""
        loc = parse_locator(locator)
        if not loc:
            raise ValueError(f"Unsupported locator: {locator}. Use e.g. (By.ID, \"login\").")
        with open_page(url, project_root(), _sess(session)) as v:
            n = count_matches(v.driver, loc)
            visible = None
            if n:
                try:
                    visible = v.driver.find_elements(loc.by, loc.value)[0].is_displayed()
                except Exception:  # noqa: BLE001
                    visible = None
            verdict = "unique" if n == 1 else "not_found" if n == 0 else "ambiguous"
            return {"url": v.final_url, "locator": render(loc), "matches": n, "visible": visible, "verdict": verdict}

    @mcp.tool(title="Save login state")
    def save_login_state(url: str, steps: list[Step], name: str = "default", success_locator: Optional[str] = None) -> dict:
        """Log in once with steps and save cookies + localStorage to .qa-mcp/auth/<name>.json for other tools.
        Use ${ENV:NAME} for credentials; values are never echoed."""
        if not re.fullmatch(r"[\w-]{1,40}", name):
            raise ValueError("name must be 1-40 letters, digits, _ or -")
        root = project_root()
        sess = {"steps": [s.model_dump(exclude_none=True) for s in steps]}
        if success_locator:
            if not parse_locator(success_locator):
                raise ValueError(f"Unsupported success_locator: {success_locator}")
            sess["steps"].append({"action": "wait_for", "locator": success_locator})
        with open_page(url, root, sess) as v:
            state = capture_storage_state(v.driver)
            out = root / ".qa-mcp" / "auth" / f"{name}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(state, indent=2), "utf8")
            _ensure_gitignored(root, ".qa-mcp/auth/")
            return {"saved": out.relative_to(root).as_posix(), "url": v.final_url, "stepsRun": v.steps,
                    "cookies": len(state["cookies"]), "localStorageOrigins": len(state["origins"]),
                    "note": "Pass it as session.storage_state. .qa-mcp/auth/ is in .gitignore; do not commit it."}

    @mcp.tool(title="Parse user story")
    def parse_user_story(story: str, url: Optional[str] = None) -> dict:
        """Turn a user story, Gherkin scenarios or acceptance criteria into scenarios and a pytest + Selenium skeleton."""
        parsed = parse_story(story)
        root = project_root()
        out = {**parsed, "skeleton": scaffold_test(parsed, url)}
        if not (root / "tests" / "conftest.py").is_file() and not (root / "conftest.py").is_file():
            out["conftest"] = CONFTEST
            out["note"] = "No conftest.py found: write this one to tests/conftest.py to provide the driver fixture."
        return out

    @mcp.tool(title="Write test")
    def write_test(path: str, code: str, overwrite: bool = False) -> dict:
        """Write a pytest file into tests/ (test_*.py, *_test.py or conftest.py). Refuses other paths; won't overwrite unless asked."""
        root = project_root()
        tests_dir = (root / "tests").resolve()
        rel = path.replace("\\", "/")
        rel = rel[len("tests/"):] if rel.startswith("tests/") else rel
        target = (tests_dir / rel).resolve()
        if tests_dir not in target.parents:
            raise ValueError("Tests can only be written inside tests/")
        if not re.fullmatch(r"(test_[\w-]+|[\w-]+_test|conftest)\.py", target.name):
            raise ValueError("File name must be test_*.py, *_test.py or conftest.py")
        if target.exists() and not overwrite:
            raise ValueError(f"{target.relative_to(root).as_posix()} exists. Pass overwrite=true to replace it.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, "utf8")
        return {"written": target.relative_to(root).as_posix(), "bytes": len(code.encode("utf8"))}

    @mcp.tool(title="Run tests")
    def run_tests(target: Optional[str] = None, keyword: Optional[str] = None, timeout_s: int = 600) -> dict:
        """Run the project's pytest suite (optionally one file/node id, or -k keyword).
        Failing tests include the exact Selenium locator they were waiting for and the page they were on."""
        root = project_root()
        targets = None
        if target:
            full = (root / target.split("::")[0]).resolve()
            if root not in full.parents and full != root:
                raise ValueError("target must be inside the project")
            targets = [target]
        return _run_tests(root, targets, keyword, max(10, min(timeout_s, 3600)))

    @mcp.tool(title="Capture baseline")
    def capture_baseline(url: str, locators: list[str], session: SessionArg = None) -> dict:
        """While tests pass, fingerprint the element each locator matches (.qa-mcp/baselines.json) so healing can find it later."""
        root = project_root()
        captured, skipped, entries = [], [], {}
        with open_page(url, root, _sess(session)) as v:
            for raw in locators:
                loc = parse_locator(raw)
                if not loc:
                    skipped.append({"locator": raw, "reason": "unsupported locator"})
                    continue
                els = v.driver.find_elements(loc.by, loc.value) if count_matches(v.driver, loc) else []
                if len(els) != 1:
                    skipped.append({"locator": render(loc), "reason": f"matches {len(els)} elements, need exactly 1"})
                    continue
                fp = fingerprint_of(v.driver, els[0])
                if fp:
                    entries[render(loc)] = fp
                    captured.append(render(loc))
            if entries:
                BaselineStore(root).put(v.final_url, entries)
            return {"page": v.final_url, "captured": captured, "skipped": skipped,
                    "file": ".qa-mcp/baselines.json", "note": "Commit .qa-mcp/baselines.json so healing works in CI."}

    @mcp.tool(title="Heal locator")
    def heal_locator(url: str, locator: str, session: SessionArg = None) -> dict:
        """Find the element a broken Selenium locator meant after a UI change and suggest a verified replacement,
        with confidence, reasons and the runner-up candidates. Never edits files."""
        loc = parse_locator(locator)
        root = project_root()
        with open_page(url, root, _sess(session)) as v:
            baseline = BaselineStore(root).get(v.final_url, render(loc)) if loc else None
            result = heal(v.driver, loc, locator, baseline)
            return {"page": v.final_url, **result}

    @mcp.prompt(title="User story to Selenium test")
    def story_to_selenium(story: str, url: str) -> str:
        """Guided workflow from a user story to a passing pytest + Selenium test."""
        return (
            f"Write a pytest + Selenium test for this user story, starting at {url}.\n\n{story}\n\n"
            "1. Call parse_user_story for scenarios and a skeleton (write the conftest it returns if there is none).\n"
            "2. Call explore_page on each page the flow reaches; use only the verified locators it returns. "
            "For pages behind a login, call save_login_state once (credentials as ${ENV:NAME}) and pass session.storage_state.\n"
            "3. Fill every TODO using explicit waits (WebDriverWait + expected_conditions), no time.sleep.\n"
            "4. Save with write_test as tests/test_<feature>.py, then run_tests. Heal locator failures with heal_locator; "
            "if the app itself is wrong, report the bug instead of weakening the assertion.\n"
            "5. When it passes, call capture_baseline with the URL and the locators the test uses."
        )

    return mcp


def serve() -> None:
    create_server().run()


__all__ = ["create_server", "serve", "VERSION"]
