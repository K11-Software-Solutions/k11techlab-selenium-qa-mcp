"""Sessions: reach pages behind a login or several steps into a flow.

A session is an optional saved login (a storage-state JSON file with cookies and
localStorage, the same format Playwright uses) plus a short list of steps run after
the first page loads. Step locators are parsed, never eval'd, and values can read
secrets from the environment with ${ENV:NAME}, so passwords never appear in tool
arguments, results or logs.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from .locators import parse_locator, render

STEP_ACTIONS = ("goto", "click", "fill", "press", "select", "check", "uncheck", "wait_for")
MAX_STEPS = 25
ENV_RE = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")
ENV_ONLY = re.compile(r"^\$\{ENV:[A-Za-z_][A-Za-z0-9_]*\}$")


def resolve_env(value: str, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env

    def sub(m: re.Match) -> str:
        if m.group(1) not in env:
            raise ValueError(f"Environment variable {m.group(1)} is not set")
        return env[m.group(1)]

    return ENV_RE.sub(sub, value)


def describe_step(step: dict[str, Any]) -> str:
    """Text safe to echo back: env placeholders kept, other fill values masked."""
    action = step.get("action")
    loc = parse_locator(step.get("locator") or "")
    target = render(loc) if loc else (step.get("locator") or "")
    if action == "goto":
        return f"goto {step.get('url')}"
    if action == "fill":
        v = step.get("value")
        shown = v if isinstance(v, str) and ENV_ONLY.match(v) else "•••"
        return f"fill {target} with {shown}"
    if action in ("press", "select"):
        return f"{action} {target} {step.get('value') or ''}".strip()
    return f"{action} {target}"


def validate_steps(steps: list[dict[str, Any]] | None) -> None:
    steps = steps or []
    if len(steps) > MAX_STEPS:
        raise ValueError(f"At most {MAX_STEPS} steps are allowed")
    for i, s in enumerate(steps, 1):
        action = s.get("action")
        where = f"Step {i} ({action})"
        if action not in STEP_ACTIONS:
            raise ValueError(f"{where}: unknown action")
        if action == "goto":
            if not s.get("url"):
                raise ValueError(f"{where}: needs url")
            continue
        if not s.get("locator"):
            raise ValueError(f"{where}: needs locator")
        if not parse_locator(s["locator"]):
            raise ValueError(f"{where}: unsupported locator {s['locator']}")
        if action in ("fill", "press", "select") and s.get("value") is None:
            raise ValueError(f"{where}: needs value")


def resolve_storage_state(root: Path, rel: str | None) -> Path | None:
    if not rel:
        return None
    root = Path(root).resolve()
    full = (root / rel).resolve()
    if full != root and root not in full.parents:
        raise ValueError("storage_state must be inside the project folder")
    if not full.is_file():
        raise ValueError(f"storage_state file not found: {rel}. Create it with save_login_state.")
    return full


def apply_storage_state(driver, path: Path, start_url: str) -> None:
    """Load cookies and localStorage into the browser before opening the start page."""
    state = json.loads(Path(path).read_text("utf8"))
    start = urlsplit(start_url)
    origins = {o.get("origin") for o in state.get("origins", []) if o.get("origin")}
    if start.scheme in ("http", "https"):
        origins.add(f"{start.scheme}://{start.netloc}")
    by_origin = {o["origin"]: o.get("localStorage", []) for o in state.get("origins", []) if o.get("origin")}
    for origin in sorted(origins):
        host = urlsplit(origin).hostname or ""
        cookies = [c for c in state.get("cookies", []) if host and host.endswith(str(c.get("domain", "")).lstrip("."))]
        items = by_origin.get(origin, [])
        if not cookies and not items:
            continue
        driver.get(origin + "/")
        for c in cookies:
            cookie = {k: c[k] for k in ("name", "value", "path", "secure", "httpOnly") if k in c}
            if c.get("expires", -1) and c.get("expires", -1) > 0:
                cookie["expiry"] = int(c["expires"])
            try:
                driver.add_cookie(cookie)
            except Exception:  # noqa: BLE001 - cookie for another subdomain
                pass
        if items:
            driver.execute_script(
                "for (const [k, v] of arguments[0]) window.localStorage.setItem(k, v);",
                [[i["name"], i["value"]] for i in items],
            )


def capture_storage_state(driver) -> dict[str, Any]:
    cookies = []
    for c in driver.get_cookies():
        out = {k: c[k] for k in ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite") if k in c}
        out["expires"] = c.get("expiry", -1)
        cookies.append(out)
    u = urlsplit(driver.current_url)
    origins = []
    if u.scheme in ("http", "https"):
        items = driver.execute_script(
            "const o = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i);"
            " o.push({name: k, value: localStorage.getItem(k)}); } return o;") or []
        origins.append({"origin": f"{u.scheme}://{u.netloc}", "localStorage": items})
    return {"cookies": cookies, "origins": origins}


KEYS = {"enter": "ENTER", "tab": "TAB", "escape": "ESCAPE", "esc": "ESCAPE", "space": "SPACE",
        "backspace": "BACKSPACE", "delete": "DELETE", "arrowdown": "ARROW_DOWN", "arrowup": "ARROW_UP",
        "arrowleft": "ARROW_LEFT", "arrowright": "ARROW_RIGHT", "home": "HOME", "end": "END",
        "pageup": "PAGE_UP", "pagedown": "PAGE_DOWN"}


def run_steps(driver, steps: list[dict[str, Any]] | None, base_url: str | None = None) -> list[str]:
    """Run steps in the browser. Errors name the step but never include secret values."""
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import Select, WebDriverWait

    validate_steps(steps)
    done = []
    for i, s in enumerate(steps or [], 1):
        label = describe_step(s)
        try:
            action = s["action"]
            if action == "goto":
                driver.get(urljoin(base_url or driver.current_url, resolve_env(s["url"])))
            else:
                loc = parse_locator(s["locator"])
                value = resolve_env(str(s["value"])) if s.get("value") is not None else None
                wait = WebDriverWait(driver, 15 if action == "wait_for" else 10)
                if action == "wait_for":
                    wait.until(EC.visibility_of_element_located((loc.by, loc.value)))
                else:
                    el = wait.until(EC.element_to_be_clickable((loc.by, loc.value)) if action in ("click", "check", "uncheck")
                                    else EC.visibility_of_element_located((loc.by, loc.value)))
                    if action == "click":
                        el.click()
                    elif action == "fill":
                        el.clear()
                        el.send_keys(value)
                    elif action == "press":
                        el.send_keys(getattr(Keys, KEYS.get(value.lower().replace(" ", ""), ""), value) if value else "")
                    elif action == "select":
                        sel = Select(el)
                        try:
                            sel.select_by_visible_text(value)
                        except Exception:  # noqa: BLE001
                            sel.select_by_value(value)
                    elif action in ("check", "uncheck") and el.is_selected() != (action == "check"):
                        el.click()
            done.append(label)
        except Exception as e:  # noqa: BLE001
            msg = (getattr(e, "msg", None) or str(e) or type(e).__name__).strip().split("\n")[0]
            raise RuntimeError(f"Step {i} failed: {label}: {type(e).__name__}{': ' + msg if msg else ''}") from None
    return done
