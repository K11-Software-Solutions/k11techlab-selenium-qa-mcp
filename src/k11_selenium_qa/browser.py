"""Browser handling: a fresh headless browser per page visit, so sessions never leak."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .session import apply_storage_state, resolve_storage_state, run_steps


def make_driver():
    """Headless Chrome by default. QA_MCP_BROWSER=chrome|edge|firefox, QA_MCP_HEADED=1 to watch."""
    from selenium import webdriver

    name = os.environ.get("QA_MCP_BROWSER", "chrome").lower()
    headed = os.environ.get("QA_MCP_HEADED") == "1"
    try:
        if name == "firefox":
            opts = webdriver.FirefoxOptions()
            if not headed:
                opts.add_argument("-headless")
            driver = webdriver.Firefox(options=opts)
        else:
            opts = webdriver.EdgeOptions() if name == "edge" else webdriver.ChromeOptions()
            if not headed:
                opts.add_argument("--headless=new")
            opts.add_argument("--window-size=1280,900")
            opts.add_argument("--disable-gpu")
            if os.environ.get("CI"):
                opts.add_argument("--no-sandbox")
                opts.add_argument("--disable-dev-shm-usage")
            driver = webdriver.Edge(options=opts) if name == "edge" else webdriver.Chrome(options=opts)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Could not start {name}: {str(e).splitlines()[0] if str(e) else type(e).__name__}. "
            "Install the browser (Chrome is the default; set QA_MCP_BROWSER=edge or firefox to switch). "
            "Selenium Manager downloads the matching driver automatically."
        ) from None
    driver.set_page_load_timeout(30)
    return driver


@dataclass
class Visit:
    driver: Any
    final_url: str
    steps: list[str] = field(default_factory=list)


def _settle(driver) -> None:
    try:
        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def open_page(url: str, root: Path, session: dict[str, Any] | None = None) -> Iterator[Visit]:
    session = session or {}
    state = resolve_storage_state(root, session.get("storage_state"))
    driver = make_driver()
    try:
        if state:
            apply_storage_state(driver, state, url)
        driver.get(url)
        _settle(driver)
        done = run_steps(driver, session.get("steps"), url)
        _settle(driver)
        yield Visit(driver, driver.current_url, done)
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass
