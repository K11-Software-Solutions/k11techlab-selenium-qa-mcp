"""heal-ci: heal broken Selenium locators in CI, with an audit trail.

  run tests → for each locator failure: open the page the test was on, heal against
  the committed baseline → apply only confident suggestions (in test files and Page
  Objects) → re-run the affected tests → revert any change whose test still fails →
  write a Markdown + JSON report for the pull request.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from .browser import open_page
from .heal import heal
from .locators import parse_locator, render
from .rewrite import Replacement, locate_in_project, replace_locator
from .runner import run_tests
from .store import BaselineStore
from .version import VERSION

DEFAULT_MIN_CONFIDENCE = 0.7
OUTCOMES = ("applied", "suggested", "reverted", "needs_review", "not_found", "skipped")


@dataclass
class HealItem:
    test: str
    file: str
    locator: str
    line: int | None = None
    page: str | None = None
    outcome: str = "skipped"
    confidence: float | None = None
    suggestion: str | None = None
    reasons: list[str] = field(default_factory=list)
    runnerUp: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    replacements: list[dict] = field(default_factory=list)
    verified: bool | None = None
    note: str | None = None


def _read(p: Path) -> str:
    with open(p, encoding="utf8", newline="") as fh:
        return fh.read()


def _write(p: Path, s: str) -> None:
    with open(p, "w", encoding="utf8", newline="") as fh:
        fh.write(s)


def load_config(root: Path, config_path: str | None = None) -> dict[str, Any]:
    f = Path(root) / (config_path or ".qa-mcp/heal.config.json")
    if not f.is_file():
        if config_path:
            raise FileNotFoundError(f"Heal config not found: {f}")
        return {}
    return json.loads(f.read_text("utf8"))


def _target_for(cfg: dict, file: str) -> dict | None:
    norm = file.replace("\\", "/")
    for t in cfg.get("targets", []):
        if norm.endswith(t.get("spec", "").replace("\\", "/")):
            return t
    return None


def heal_ci(root: Path, apply: bool, min_confidence: float | None = None, config_path: str | None = None,
            report_dir: str | None = None, verify: bool = True, log: Callable[[str], None] = lambda m: None,
            extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    cfg = load_config(root, config_path)
    min_conf = min_confidence if min_confidence is not None else cfg.get("minConfidence", DEFAULT_MIN_CONFIDENCE)
    store = BaselineStore(root)

    log("Running tests…")
    run = run_tests(root, extra_env=extra_env)
    if run.get("error"):
        raise RuntimeError(f"{run['error']}\n{run.get('output', '')}".strip())
    failing = [t for t in run["tests"] if t["status"] in ("failed", "error")]
    items: list[HealItem] = []
    other: list[dict] = []
    originals: dict[Path, str] = {}
    current: dict[Path, str] = {}
    applied: dict[str, list[HealItem]] = {}  # node id -> items applied for it
    item_files: dict[int, list[Path]] = {}

    for t in failing:
        if not t.get("failingLocator"):
            other.append({"test": t["test"], "file": t["file"], "error": t.get("error")})
            continue
        broken = parse_locator(t["failingLocator"])
        item = HealItem(test=t["test"], file=t["file"], locator=t["failingLocator"], line=t.get("locatorLine") or t.get("errorLine"))
        items.append(item)
        if broken is None:
            item.note = "Locator form not supported for healing"
            continue
        target = _target_for(cfg, t["file"]) or {}
        raw_url = target.get("url") or t.get("page")
        if not raw_url or raw_url.startswith(("data:", "about:")):
            item.note = "Could not tell which page the test was on. Add a target with a url in .qa-mcp/heal.config.json."
            continue
        url = urljoin(cfg.get("baseUrl") or raw_url, raw_url)
        session = target.get("session") or cfg.get("session")
        log(f"Healing {render(broken)} on {url}")
        try:
            with open_page(url, root, session) as v:
                item.page = v.final_url
                baseline = store.get(v.final_url, render(broken))
                result = heal(v.driver, broken, render(broken), baseline)
        except Exception as e:  # noqa: BLE001
            item.note = f"Could not open the page: {str(e).splitlines()[0]}"
            continue
        cands = result.get("candidates") or []
        item.confidence = result.get("confidence")
        item.suggestion = result.get("suggestion")
        item.reasons = result.get("reasons") or []
        item.candidates = cands
        item.runnerUp = {"locator": cands[1]["locator"], "score": cands[1]["score"]} if len(cands) > 1 else None
        status = result["status"]
        if status == "healthy":
            item.note = "Locator matches on the page now; the failure has another cause."
            continue
        if status == "not_found":
            item.outcome, item.note = "not_found", result.get("note")
            continue
        if status != "healed" or not item.suggestion or (item.confidence or 0) < min_conf:
            item.outcome = "needs_review"
            item.note = f"Confidence below the {min_conf} threshold for automatic changes." if status == "healed" else result.get("note")
            continue
        healed = parse_locator(item.suggestion)
        files = locate_in_project(root, broken, prefer=Path(t["filePath"]))
        reps: list[Replacement] = []
        new_code: dict[Path, str] = {}
        for f in files:
            src = current.get(f) or _read(f)
            code, r = replace_locator(src, broken, healed, f.relative_to(root).as_posix())
            if r:
                new_code[f] = code
                reps += r
        if not reps:
            item.outcome, item.note = "needs_review", "Locator text not found in the project source (built dynamically?)."
            continue
        item.replacements = [asdict(r) for r in reps]
        if not apply:
            item.outcome = "suggested"
            continue
        for f, code in new_code.items():
            originals.setdefault(f, current.get(f) or _read(f))
            _write(f, code)
            current[f] = code
        item.outcome = "applied"
        item_files[id(item)] = list(new_code)
        applied.setdefault(t["test"], []).append(item)

    if apply and verify and applied:
        for rnd in range(1, 4):
            log(f"Re-running healed tests (round {rnd})…")
            rerun = run_tests(root, targets=sorted(applied), extra_env=extra_env)
            passed = {r["test"] for r in rerun.get("tests", []) if r["status"] == "passed"}
            dropped = False
            for node in list(applied):
                for it in applied[node]:
                    it.verified = node in passed
                    if not it.verified:
                        it.outcome = "reverted"
                        it.note = "Healed test still failed on re-run; this change was reverted (other changes were kept)."
                        dropped = True
                if node not in passed:
                    del applied[node]
            if not dropped:
                break
            # Rebuild touched files from the originals with only the kept changes.
            kept = [it for its in applied.values() for it in its]
            for f, orig in originals.items():
                code = orig
                for it in kept:
                    if f in item_files.get(id(it), []):
                        code, _ = replace_locator(code, parse_locator(it.locator), parse_locator(it.suggestion))
                _write(f, code)
                current[f] = code
            if not applied:
                break

    counts = {o: sum(1 for i in items if i.outcome == o) for o in OUTCOMES}
    report = {
        "tool": f"k11-selenium-qa-mcp heal-ci {VERSION}",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "apply" if apply else "dry-run",
        "minConfidence": min_conf,
        "testsRun": run.get("total", 0),
        "failures": len(failing),
        "items": [asdict(i) for i in items],
        "otherFailures": other,
        "counts": counts,
    }
    out_dir = root / (report_dir or ".qa-mcp/heal-report")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "heal-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf8")
    (out_dir / "heal-report.md").write_text(to_markdown(report), "utf8")
    return {"report": report, "markdownPath": str(out_dir / "heal-report.md"), "jsonPath": str(out_dir / "heal-report.json")}


def _code(s: str | None) -> str:
    return f"`{s.replace('`', chr(39))}`" if s else "–"


def _pct(n: float | None) -> str:
    return "–" if n is None else f"{round(n * 100)}%"


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def to_markdown(r: dict[str, Any]) -> str:
    c = r["counts"]
    L = ["## Locator healing report", ""]
    L.append(f"{_n(r['testsRun'], 'test', 'tests')} run, {r['failures']} failed. "
             f"**{c['applied']} healed and verified**, {c['suggested']} suggested, {c['reverted']} reverted, "
             f"{_n(c['needs_review'], 'needs', 'need')} review, {c['not_found']} not found, "
             f"{_n(len(r['otherFailures']), 'failure', 'failures')} not caused by locators.")
    L += ["", f"Mode: **{r['mode']}**. Changes are applied only when confidence is at least **{_pct(r['minConfidence'])}**, "
              "clearly ahead of the runner-up, and the healed test passes on re-run.", ""]
    changed = [i for i in r["items"] if i["outcome"] in ("applied", "suggested")]
    if changed:
        L += ["### Changes" if r["mode"] == "apply" else "### Suggested changes", "",
              "| Test | Where | Old locator | New locator | Confidence | Runner-up | Re-run |", "|---|---|---|---|---|---|---|"]
        for i in changed:
            where = ", ".join(sorted({f"{x['file']}:{x['line']}" for x in i["replacements"]}))
            ru = f"{_code(i['runnerUp']['locator'])} ({_pct(i['runnerUp']['score'])})" if i.get("runnerUp") else "–"
            rerun = "passed" if i.get("verified") is True else "failed" if i.get("verified") is False else "not run"
            L.append(f"| {i['test']} | {where} | {_code(i['locator'])} | {_code(i['suggestion'])} | {_pct(i['confidence'])} | {ru} | {rerun} |")
        L.append("")
        for i in changed:
            L += [f"<details><summary>Why {_code(i['suggestion'])} replaces {_code(i['locator'])}</summary>", "",
                  f"Page: {i.get('page') or '–'}", ""]
            L += [f"- {reason}" for reason in i["reasons"]]
            L += ["", "</details>", ""]
    review = [i for i in r["items"] if i["outcome"] not in ("applied", "suggested")]
    if review:
        L += ["### Needs a person", "", "| Test | Locator | Outcome | Best candidate | Note |", "|---|---|---|---|---|"]
        for i in review:
            best = i["candidates"][0] if i.get("candidates") else None
            bc = f"{_code(best['locator'])} ({_pct(best['score'])})" if best else "–"
            L.append(f"| {i['test']} | {_code(i['locator'])} | {i['outcome'].replace('_', ' ')} | {bc} | {i.get('note') or ''} |")
        L.append("")
    if r["otherFailures"]:
        L += ["### Failures not caused by locators", "", "These may be real bugs and were not touched:", ""]
        L += [f"- **{f['test']}**: {f.get('error') or 'see test output'}" for f in r["otherFailures"]]
        L.append("")
    L += [f"<sub>Generated by {r['tool']} at {r['generatedAt']}. Full evidence: heal-report.json.</sub>", ""]
    return "\n".join(L)
