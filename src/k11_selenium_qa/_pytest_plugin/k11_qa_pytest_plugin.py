"""pytest plugin loaded by k11 Selenium QA when it runs your tests (``-p k11_qa_pytest_plugin``).

It records, for each failing test, the last Selenium locator that could not be found,
the line in your code that asked for it, and the page the browser was on. Results are
written as JSON to the path in K11_QA_RESULTS. It changes nothing about how tests run.
Self-contained on purpose: it is put on PYTHONPATH for the project's own interpreter.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_results: list[dict] = []
_current: dict = {"file": None, "failed": None}


def _record_failure(driver, by, value):
    line = None
    f = sys._getframe(2)
    test_file = _current.get("file")
    first_user = None
    while f is not None:
        fn = os.path.normcase(os.path.abspath(f.f_code.co_filename))
        if test_file and fn == test_file:
            line = f.f_lineno
            break
        if first_user is None and "site-packages" not in fn and "selenium" not in fn and "k11_qa_pytest_plugin" not in fn:
            first_user = (fn, f.f_lineno)
        f = f.f_back
    try:
        url = driver.current_url
    except Exception:  # noqa: BLE001
        url = None
    _current["failed"] = {"by": by, "value": value, "line": line, "url": url,
                          "where": f"{first_user[0]}:{first_user[1]}" if first_user else None}


def _install() -> None:
    try:
        from selenium.common.exceptions import NoSuchElementException
        from selenium.webdriver.remote.webdriver import WebDriver
        from selenium.webdriver.remote.webelement import WebElement
    except ImportError:
        return
    if getattr(WebDriver.find_element, "_k11", False):
        return

    def wrap(orig, is_driver):
        def find_element(self, by="id", value=None):
            try:
                el = orig(self, by, value)
            except NoSuchElementException:
                _record_failure(self if is_driver else self.parent, by, value)
                raise
            failed = _current.get("failed")
            if failed and failed["by"] == by and failed["value"] == value:
                _current["failed"] = None  # found after waiting: not the cause
            return el

        find_element._k11 = True
        return find_element

    WebDriver.find_element = wrap(WebDriver.find_element, True)
    WebElement.find_element = wrap(WebElement.find_element, False)


_install()


def pytest_runtest_setup(item):
    _current["file"] = os.path.normcase(os.path.abspath(str(item.fspath)))
    _current["failed"] = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" or (rep.failed and rep.when == "setup") or (rep.skipped and rep.when == "setup"):
        entry = {
            "nodeid": item.nodeid,
            "name": item.name,
            "file": os.path.abspath(str(item.fspath)),
            "line": (item.location[1] or 0) + 1,
            "outcome": rep.outcome if rep.when == "call" else ("error" if rep.failed else "skipped"),
            "duration": round(rep.duration, 3),
        }
        if rep.failed and call.excinfo is not None:
            exc = call.excinfo.value
            msg = (getattr(exc, "msg", None) or str(exc) or "").strip()
            entry["error"] = f"{call.excinfo.typename}: {msg.splitlines()[0] if msg else ''}".strip().rstrip(":")
            entry["errorType"] = call.excinfo.typename
            tb = call.excinfo.traceback
            for e in reversed(tb):
                if os.path.normcase(os.path.abspath(str(e.path))) == _current["file"]:
                    entry["errorLine"] = e.lineno + 1
                    break
            failed = _current.get("failed")
            if failed and call.excinfo.typename in ("NoSuchElementException", "TimeoutException"):
                entry["failingLocator"] = {"by": failed["by"], "value": failed["value"]}
                entry["page"] = failed["url"]
                if failed.get("line"):
                    entry["locatorLine"] = failed["line"]
        _results[:] = [r for r in _results if r["nodeid"] != item.nodeid] + [entry]


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("K11_QA_RESULTS")
    if path:
        with open(path, "w", encoding="utf8") as fh:
            json.dump({"tests": _results, "exitstatus": int(exitstatus)}, fh, indent=2)
