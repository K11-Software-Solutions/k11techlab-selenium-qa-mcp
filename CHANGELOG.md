# Changelog

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
