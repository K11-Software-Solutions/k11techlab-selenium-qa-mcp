# Changelog

## Unreleased

- **Ask before you build:** new `review_user_story` tool. Before tests are generated, it lists the questions a careful tester would ask (missing acceptance criteria, outcomes that can't be asserted, no user role, untestable words, limits without numbers, no failure path, missing preconditions, and, with `context`, terms the context never explains), each with why it matters and the words that raised it.
- `/story-to-test` and the `story_to_selenium` prompt now start with the review and wait for answers instead of guessing; open questions the user chooses to skip go into the test and the final report.
- `parse_user_story` returns a short `review` summary, so open questions are visible even when the review is skipped.
- The rules match k11 Playwright QA 0.4.1 exactly: both projects test against the same cases (`tests/fixtures/review_cases.json`).

## 0.2.2 (16 November 2026)

- **Fix:** heal-ci could revert a correct heal. When a locator change kept the Page Object's size (e.g. `"view-orders"` → `"show-orders"`) and was written within the same second as the last test run, Python reused the old bytecode, the re-run used the old locator, and the fix was reverted. Seen on fast CI machines. heal-ci now deletes the bytecode of every file it edits, and tests run with `PYTHONDONTWRITEBYTECODE=1`.

## 0.2.1 (13 November 2026)

- The server now reports its own version (`0.2.1`) to MCP clients and directories, instead of the MCP SDK's version.

## 0.2.0 (13 November 2026): Java support

- **Java projects:** JUnit 5 and TestNG suites run with Maven or Gradle (or their wrappers). The project's language is detected from `pom.xml` / `build.gradle`, or set with `QA_MCP_LANGUAGE`.
- **Java locators everywhere:** `By.id(...)`-style calls, `@FindBy(...)` (including `how = How.X, using = "..."`), and `By.toString()` from Selenium exceptions. Tools return locators in the project's language.
- **heal-ci for Java:** edits `By` calls and `@FindBy` annotations in tests and Page Objects, re-runs the healed tests, reverts any that still fail. For Java runs, the page is found from the locator's baseline.
- **Story to test:** JUnit 5 or TestNG skeletons (`package` and `class_name` options); `write_test` writes `.java` files under `src/test/java/` only.
- Baselines use one canonical key, so Python and Java suites for the same app can share `.qa-mcp/baselines.json`.

## 0.1.0 (13 November 2026): first release

- MCP tools: `explore_page`, `check_locator`, `save_login_state`, `parse_user_story`, `write_test`, `run_tests`, `capture_baseline`, `heal_locator`; `/story-to-test` and `/heal-tests` plugin commands.
- Self-healing locators with confidence, reasons and the runner-up; `heal-ci` with verified changes and an audit report for pull requests.
- Sessions with saved logins and steps; secrets via `${ENV:NAME}`.
