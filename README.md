# k11 Selenium QA — MCP server & Claude Code plugin

**Self-healing Selenium tests with an audit trail. No vendor lock-in, no rewrite to Playwright.**

Most Selenium suites break the same way: someone renames an id, and dozens of `find_element(By.ID, ...)` calls fail overnight. AI assistants can write Selenium tests, but they guess locators, and healing tools usually patch things at runtime without telling you what changed. This MCP server gives the assistant facts instead of guesses, and gives your team a reviewable record of every fix:

- **Verified locators.** It opens the real page in Selenium and returns locators that match exactly one element, most stable first: `data-testid`, a stable `id`, `name`, link text, `aria-label`, then text-based XPath.
- **Story → pytest.** It turns "As a… I want… so that…", Gherkin scenarios or acceptance-criteria bullets into a pytest + Selenium skeleton: one test per scenario, explicit waits, and a `driver` fixture if you don't have one.
- **Structured test runs.** It runs your pytest suite and reports, for each failure, the exact locator Selenium could not find, the line that asked for it, and the page the browser was on.
- **Self-healing with evidence.** When the UI changes, it finds the element the test meant and suggests a verified replacement, with a confidence score, the reasons and the runner-up.
- **Healing in CI.** `heal-ci` applies only confident fixes, edits your tests *and Page Objects*, re-runs them, reverts anything that still fails, and opens a pull request whose description is the audit report.

Works with **Claude Code** (as a plugin with `/story-to-test` and `/heal-tests`), **Claude Desktop**, and any MCP client. Python 3.10+, Selenium 4.

---

## See it heal in CI

The demo app's account page was redesigned: ids renamed, a "View returns" button added next to "View orders", "Edit profile" renamed to "Account settings", the cart message reworded and the page title changed. The Selenium suite uses a Page Object:

```python
class AccountPage:
    VIEW_ORDERS = (By.ID, "view-orders")
    OPEN_CART = (By.ID, "cart-btn")
```

`k11-selenium-qa-mcp heal-ci --apply` produced this pull-request description (trimmed):

> **1 healed and verified**, 0 suggested, 1 reverted, 1 needs review, 0 not found, 1 failure not caused by locators.
>
> | Test | Where | Old locator | New locator | Confidence | Runner-up | Re-run |
> |---|---|---|---|---|---|---|
> | test_shows_my_orders | tests/pages/account_page.py:7 | `(By.ID, "view-orders")` | `(By.ID, "orders-toggle")` | 82% | `(By.ID, "returns-toggle")` (59%) | passed |
>
> Why: name matches, role matches, text matches, type matches, tag matches; classes similar (43%).
>
> **Needs a person:** "Edit profile" → best candidate "Account settings" at 45%, not confident enough to change. `(By.ID, "cart-btn")` healed at 85%, but the test still failed because the cart message changed too, so the change was **reverted**.
>
> **Not caused by locators:** `test_has_the_account_title` (the page title changed). Untouched: it may be a real bug.

It picked "View orders" over the look-alike "View returns", fixed it where it lives (the Page Object, not the test), and refused to guess where a person should decide.

## Tools

| Tool | What it does |
|---|---|
| `explore_page` | Opens a URL and lists elements with Selenium locators verified to match exactly one element. |
| `check_locator` | Counts what a locator matches on a page (1 = good) and whether it's visible. |
| `parse_user_story` | User story → scenarios + a pytest/Selenium skeleton (and a `conftest.py` if you need one). |
| `write_test` | Writes `test_*.py`, `*_test.py` or `conftest.py` into `tests/`. Refuses other paths; won't overwrite unless asked. |
| `run_tests` | Runs pytest and returns per-test results with the failing locator, its line and the page. |
| `capture_baseline` | While tests pass, fingerprints the element each locator matches (`.qa-mcp/baselines.json`). |
| `heal_locator` | Finds the intended element after a UI change and suggests a verified replacement. |
| `save_login_state` | Logs in once with a few steps and saves cookies + localStorage for the other tools. |

Locators are written the way your code writes them: `(By.ID, "email")`, `driver.find_element(By.XPATH, "//button[...]")`, or `(By.CSS_SELECTOR, "[data-testid='save']")`.

Prompt: **`story_to_selenium`**, a guided workflow from story to passing test.

## How self-healing works

1. **Baseline.** While tests pass, `capture_baseline` records each element's fingerprint: role, accessible name, test id, id, `name`, type, label, placeholder, classes, text and href.
2. **Detect.** `run_tests` loads a small pytest plugin that notes the last locator Selenium could not find, including inside `WebDriverWait` and expected conditions, and the page the browser was on.
3. **Match.** `heal_locator` scores every visible element on the current page against the fingerprint, with exact matching for stable attributes and fuzzy, synonym-aware matching for text and ids ("Sign in" ≈ "Log in", `btn` ≈ `button`).
4. **Verify.** The best match gets the most stable Selenium locator that matches exactly one element on the live page.
5. **Decide.** `healed` only when confidence is at least 0.55 and clearly ahead of the runner-up; otherwise `needs_review` with candidates, or `not_found`. Without a baseline it falls back to what the locator implies, and says so.

Commit `.qa-mcp/baselines.json`. Do **not** commit `.qa-mcp/auth/` (saved logins); `save_login_state` adds it to `.gitignore`.

## Pages behind a login and multi-step flows

Every page tool accepts a `session`:

```json
{
  "url": "https://shop.example.com/account",
  "session": {
    "storage_state": ".qa-mcp/auth/default.json",
    "steps": [
      { "action": "click", "locator": "(By.LINK_TEXT, \"My orders\")" },
      { "action": "wait_for", "locator": "(By.CSS_SELECTOR, \"[data-testid='order-history']\")" }
    ]
  }
}
```

- **`storage_state`**: cookies and localStorage saved by `save_login_state`, in the same JSON format Playwright uses. It must be inside the project.
- **`steps`**: `goto`, `click`, `fill`, `press`, `select`, `check`, `uncheck`, `wait_for`, up to 25, with explicit waits.
- **Secrets stay out of prompts and logs.** Write `"value": "${ENV:APP_PASSWORD}"`. Results show the placeholder; literal fill values are masked as `•••`.

## Healing in CI, with an audit trail

```bash
k11-selenium-qa-mcp heal-ci --apply
```

1. Runs your pytest suite with the locator-recording plugin.
2. For each locator failure, opens the page the test was on (logging in first if `.qa-mcp/heal.config.json` says how) and heals against the committed baseline.
3. Applies a change only when confidence is at least **0.7** (`--min-confidence`) and clearly ahead of the runner-up. It edits every place the locator literal appears: tests, Page Objects, helpers.
4. **Re-runs the affected tests and reverts any change whose test still fails**, keeping the others.
5. Leaves failures that aren't about locators alone.
6. Writes `heal-report.md` (the pull-request body) and `heal-report.json` (full evidence), plus GitHub Actions outputs.

Without `--apply` it's a dry run. Copy [`docs/heal-locators.yml`](docs/heal-locators.yml) into `.github/workflows/` to run it nightly and open the pull request, and [`docs/heal.config.example.json`](docs/heal.config.example.json) to `.qa-mcp/heal.config.json`.

## Install

Requires Python 3.10+ and Chrome (or Edge/Firefox with `QA_MCP_BROWSER=edge|firefox`). Selenium Manager downloads the matching driver automatically.

### Claude Code: plugin (recommended)

Adds the MCP tools plus `/story-to-test` and `/heal-tests` (needs [uv](https://docs.astral.sh/uv/)):

```text
/plugin marketplace add K11-Software-Solutions/k11techlab-selenium-qa-mcp
/plugin install selenium-qa@k11-selenium-qa
```

### Claude Code: MCP server only

From your test project's folder:

```bash
claude mcp add selenium-qa -- uvx --from git+https://github.com/K11-Software-Solutions/k11techlab-selenium-qa-mcp k11-selenium-qa-mcp
```

Or with pip: `pip install git+https://github.com/K11-Software-Solutions/k11techlab-selenium-qa-mcp`, then `claude mcp add selenium-qa -- k11-selenium-qa-mcp`.

### Claude Desktop and other MCP clients

```json
{
  "mcpServers": {
    "selenium-qa": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/K11-Software-Solutions/k11techlab-selenium-qa-mcp", "k11-selenium-qa-mcp"],
      "env": { "QA_MCP_ROOT": "/path/to/your/tests/project" }
    }
  }
}
```

The server works on the project in `QA_MCP_ROOT`, or the current directory. Tests run with the project's own interpreter: `QA_MCP_PYTHON`, else `.venv`/`venv` in the project, else the server's Python. That environment needs `pytest` and `selenium`.

## Try the demo

```bash
python demo/server.py --version v1      # http://127.0.0.1:8765/login.html (alex@example.com / correct-horse)
python demo/server.py --version v2      # the redesign
```

## Safety

- **Locators are parsed, never `eval`'d.** Only `By.<STRATEGY>, "<string>"` forms (and the WebDriver strategy names) are accepted.
- **Writes are confined to `tests/`** (`write_test`) or to the exact locator literal (`heal-ci`), which is found with Python's tokenizer, so comments and other code are never touched. Line endings are preserved.
- **Tests run without a shell,** with the project's interpreter.
- **Healing only suggests** in the MCP tools. `heal-ci --apply` changes code only for confident, verified fixes, and every change is in a pull request for review.

## How it compares

| | Runtime self-healing tools | k11 Selenium QA |
|---|---|---|
| Where the fix goes | Patched in memory during the run | Your source (tests and Page Objects), in a pull request |
| Evidence | Logs | Confidence, reasons and runner-up in a report |
| If the fix is wrong | Test passes against the wrong element | Re-run must pass, or the change is reverted |
| Lock-in | Proxy, agent or SDK in your test run | A pytest plugin used only while healing; nothing in your code depends on it |

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # bin/pip on macOS/Linux
pytest        # unit, real-browser, MCP protocol and heal-ci tests (27)
```

## Roadmap

- Java (JUnit 5 / TestNG) and C# (NUnit) test projects
- Healing for chained `find_element` calls and `find_elements(...)[n]`
- Visual (screenshot) fingerprints as an extra signal
- PyPI release (`uvx k11-selenium-qa-mcp`)

---

Built by [K11 Software Solutions](https://k11softwaresolutions.com). Part of the K11 Tech Lab agentic QA series, alongside [k11 Playwright QA](https://github.com/K11-Software-Solutions/k11techlab-playwright-qa-mcp). MIT licensed.
