---
description: Run Selenium tests and repair locators broken by UI changes
argument-hint: [test file or node id]
---

Repair Selenium tests whose locators broke because the UI changed, using the selenium-qa MCP tools.

Input: $ARGUMENTS (optional test file or pytest node id)

1. Call `run_tests` (for the given target, if any).
2. For each failure with a `failingLocator`, call `heal_locator` with the `page` it reports. If the page needs a login or steps to reach, pass a `session` (check `.qa-mcp/heal.config.json` first).
3. Act on the result:
   - `healed`: replace the old locator with `suggestion` where it is defined (often a Page Object, not the test).
   - `needs_review` or `ambiguous`: show the user the candidates, scores and reasons, and ask which is right before editing.
   - `not_found`: the element may have been removed. Report it; do not invent a locator.
4. Leave failures that are not locator problems untouched and list them separately; they may be real bugs.
5. Re-run the affected tests. When they pass, call `capture_baseline` to refresh fingerprints.

Finish with a table: test, old locator, new locator, confidence, and status.

To do this unattended in CI with a pull request and audit report, use `k11-selenium-qa-mcp heal-ci --apply` (see the README).
