# k11 Selenium QA — MCP server & Claude Code plugin

<!-- mcp-name: io.github.K11-Software-Solutions/selenium-qa -->

**Self-healing Selenium tests with an audit trail, for Python and Java. No vendor lock-in, no rewrite to Playwright.**

Most Selenium suites break the same way: someone renames an id, and dozens of `find_element(By.ID, ...)` calls fail overnight. AI assistants can write Selenium tests, but they guess locators, and healing tools usually patch things at runtime without telling you what changed. This MCP server gives the assistant facts instead of guesses, and gives your team a reviewable record of every fix:

- **Verified locators.** It opens the real page in Selenium and returns locators that match exactly one element, most stable first: `data-testid`, a stable `id`, `name`, link text, `aria-label`, then text-based XPath. They come back in your project's language: `(By.ID, "email")` for Python, `By.id("email")` for Java.
- **Story → test.** It turns "As a… I want… so that…", Gherkin scenarios or acceptance-criteria bullets into a **pytest**, **JUnit 5** or **TestNG** skeleton: one test per scenario, explicit waits, and driver setup.
- **Structured test runs.** It runs your suite (pytest, Maven or Gradle) and reports, for each failure, the exact locator Selenium could not find and the line that asked for it, even inside a Page Object.
- **Self-healing with evidence.** When the UI changes, it finds the element the test meant and suggests a verified replacement, with a confidence score, the reasons and the runner-up.
- **Healing in CI.** `heal-ci` applies only confident fixes, edits your tests *and Page Objects* (including `@FindBy` annotations), re-runs them, reverts anything that still fails, and opens a pull request whose description is the audit report.

Works with **Claude Code** (as a plugin with `/story-to-test` and `/heal-tests`), **Claude Desktop**, and any MCP client. The server runs on Python 3.10+; your tests can be **Python (pytest)** or **Java (JUnit 5 / TestNG, Maven or Gradle)**, Selenium 4.

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

The same redesign against the **Java** version of the suite (Maven + JUnit 5, Page Factory):

```java
@FindBy(id = "view-orders")
private WebElement viewOrders;
```

> | Test | Where | Old locator | New locator | Confidence | Runner-up | Re-run |
> |---|---|---|---|---|---|---|
> | com.acme.AccountTest#showsMyOrders | src/test/java/com/acme/pages/AccountPage.java:14 | `By.id("view-orders")` | `By.id("orders-toggle")` | 82% | `By.id("returns-toggle")` (59%) | passed |

The annotation became `@FindBy(id = "orders-toggle")`; the cart change was reverted and "Edit profile" was left for a person, exactly as in Python.

## Tools

| Tool | What it does |
|---|---|
| `explore_page` | Opens a URL and lists elements with Selenium locators verified to match exactly one element. |
| `check_locator` | Counts what a locator matches on a page (1 = good) and whether it's visible. |
| `parse_user_story` | User story → scenarios + a pytest, JUnit 5 or TestNG skeleton (and a `conftest.py` for pytest if you need one). |
| `write_test` | Python: `test_*.py`, `*_test.py` or `conftest.py` into `tests/`. Java: `.java` files into `src/test/java/`. Refuses other paths; won't overwrite unless asked. |
| `run_tests` | Runs pytest, Maven or Gradle and returns per-test results with the failing locator and where it's used. |
| `capture_baseline` | While tests pass, fingerprints the element each locator matches (`.qa-mcp/baselines.json`). |
| `heal_locator` | Finds the intended element after a UI change and suggests a verified replacement. |
| `save_login_state` | Logs in once with a few steps and saves cookies + localStorage for the other tools. |

Locators are written the way your code writes them. Python: `(By.ID, "email")`, `driver.find_element(By.XPATH, "//button[...]")`. Java: `By.id("email")`, `driver.findElement(By.cssSelector("..."))`, `@FindBy(id = "email")`, `@FindBy(how = How.ID, using = "email")`. The project's language is detected from `pom.xml` / `build.gradle` (override with `QA_MCP_LANGUAGE=python|java`).

Prompt: **`story_to_selenium`**, a guided workflow from story to passing test.

## How self-healing works

1. **Baseline.** While tests pass, `capture_baseline` records each element's fingerprint: role, accessible name, test id, id, `name`, type, label, placeholder, classes, text and href.
2. **Detect.** For pytest, a small plugin notes the last locator Selenium could not find (including inside `WebDriverWait`) and the page the browser was on. For Java, the locator comes from Selenium's own exception text in the JUnit XML reports, and the stack trace shows which Page Object or test asked for it.
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

1. Runs your suite: pytest with the locator-recording plugin, or `mvn test` / `gradle test`.
2. For each locator failure, opens the page the test was on and heals against the committed baseline. The page comes from `.qa-mcp/heal.config.json`, the pytest run, or the page that locator's baseline was captured on (how Java projects find it). It logs in first if the config says how.
3. Applies a change only when confidence is at least **0.7** (`--min-confidence`) and clearly ahead of the runner-up. It edits every place the locator appears: tests, Page Objects, helpers, `@FindBy` annotations.
4. **Re-runs the affected tests and reverts any change whose test still fails**, keeping the others.
5. Leaves failures that aren't about locators alone.
6. Writes `heal-report.md` (the pull-request body) and `heal-report.json` (full evidence), plus GitHub Actions outputs.

Without `--apply` it's a dry run. Copy [`docs/heal-locators.yml`](docs/heal-locators.yml) into `.github/workflows/` to run it nightly and open the pull request, and [`docs/heal.config.example.json`](docs/heal.config.example.json) to `.qa-mcp/heal.config.json`.

## Install

Requires Python 3.10+ and Chrome (or Edge/Firefox with `QA_MCP_BROWSER=edge|firefox`). Selenium Manager downloads the matching driver automatically. For Java projects, Maven or Gradle (or their wrappers, `mvnw` / `gradlew`) must be available.

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

The server works on the project in `QA_MCP_ROOT`, or the current directory. Python tests run with the project's own interpreter: `QA_MCP_PYTHON`, else `.venv`/`venv` in the project, else the server's Python (it needs `pytest` and `selenium`). Java tests run with the project's Maven or Gradle wrapper if present, else `mvn` / `gradle`.

## Try the demo

```bash
python demo/server.py --version v1      # http://127.0.0.1:8765/login.html (alex@example.com / correct-horse)
python demo/server.py --version v2      # the redesign
```

## Safety

- **Locators are parsed, never `eval`'d.** Only single `By` locator forms and `@FindBy` annotations with string literals are accepted.
- **Writes are confined to `tests/` or `src/test/java/`** (`write_test`) or to the exact locator (`heal-ci`), found with Python's tokenizer or a comment-aware Java scanner, so comments and other code are never touched. Line endings are preserved.
- **Tests run without a shell.** Java test filters are checked against a strict pattern.
- **Healing only suggests** in the MCP tools. `heal-ci --apply` changes code only for confident, verified fixes, and every change is in a pull request for review.

## How it compares

| | Runtime self-healing tools | k11 Selenium QA |
|---|---|---|
| Where the fix goes | Patched in memory during the run | Your source (tests and Page Objects), in a pull request |
| Evidence | Logs | Confidence, reasons and runner-up in a report |
| If the fix is wrong | Test passes against the wrong element | Re-run must pass, or the change is reverted |
| Lock-in | Proxy, agent or SDK in your test run | Nothing in your code depends on it (a pytest plugin is loaded only while it runs your tests) |

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # bin/pip on macOS/Linux
pytest        # unit, real-browser, MCP protocol, Java and heal-ci tests (41; the Maven test needs mvn)
```

## Roadmap

- C# (NUnit) test projects
- Recording the page URL for Java runs (today it comes from baselines or the config)
- Healing for chained `find_element` calls and `find_elements(...)[n]`
- Visual (screenshot) fingerprints as an extra signal
- PyPI release (`uvx k11-selenium-qa-mcp`)

---

Built by [K11 Software Solutions](https://k11softwaresolutions.com). Part of the K11 Tech Lab agentic QA series, alongside [k11 Playwright QA](https://github.com/K11-Software-Solutions/k11techlab-playwright-qa-mcp). MIT licensed.
