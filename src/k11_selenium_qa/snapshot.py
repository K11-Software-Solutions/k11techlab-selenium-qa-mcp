"""Page exploration: fingerprint meaningful elements and propose verified Selenium locators.

The fingerprinting script runs in the browser through ``execute_script`` and is the
same logic as the k11 Playwright QA server, so baselines mean the same thing.
"""

from __future__ import annotations

from typing import Any

from .locators import PRIORITY, Loc, count_matches, css_attr, render, stable_id, xpath_lit

COLLECT_JS = r"""
const maxElements = arguments[0];
const SELECTOR = ["a[href]", "button", "input", "select", "textarea", "[role]", "h1", "h2", "h3",
  "[data-testid]", "[data-test]", "[data-qa]", "label", "img[alt]", "[contenteditable=true]",
  "[data-qa-mcp-probe]"].join(",");
const clean = (s) => (s == null ? "" : String(s)).replace(/\s+/g, " ").trim();
const implicitRole = (el) => {
  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute("type") || "text").toLowerCase();
  if (el.getAttribute("role")) return el.getAttribute("role");
  if (tag === "a" && el.hasAttribute("href")) return "link";
  if (tag === "button") return "button";
  if (tag === "select") return el.multiple ? "listbox" : "combobox";
  if (tag === "textarea") return "textbox";
  if (/^h[1-6]$/.test(tag)) return "heading";
  if (tag === "img" && el.getAttribute("alt")) return "img";
  if (tag === "input") {
    if (["submit", "button", "reset", "image"].includes(type)) return "button";
    if (type === "checkbox") return "checkbox";
    if (type === "radio") return "radio";
    if (type === "number") return "spinbutton";
    if (type === "range") return "slider";
    if (["text", "email", "search", "tel", "url", "password"].includes(type)) return type === "search" ? "searchbox" : "textbox";
  }
  return undefined;
};
const labelFor = (el) => {
  const id = el.getAttribute("id");
  if (id) {
    const l = document.querySelector('label[for="' + CSS.escape(id) + '"]');
    if (l) return clean(l.textContent);
  }
  const wrap = el.closest("label");
  return wrap ? clean(wrap.textContent) : "";
};
const accName = (el) => {
  const aria = el.getAttribute("aria-label");
  if (aria) return clean(aria);
  const by = el.getAttribute("aria-labelledby");
  if (by) return clean(by.split(/\s+/).map((i) => (document.getElementById(i) || {}).textContent || "").join(" "));
  const tag = el.tagName.toLowerCase();
  if (["input", "select", "textarea"].includes(tag)) {
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (["submit", "button", "reset"].includes(type)) return clean(el.value);
    return labelFor(el) || clean(el.getAttribute("title")) || clean(el.getAttribute("placeholder"));
  }
  if (tag === "img") return clean(el.getAttribute("alt"));
  return clean(el.innerText != null ? el.innerText : el.textContent) || clean(el.getAttribute("title"));
};
const out = [];
const els = Array.from(document.querySelectorAll(SELECTOR));
for (let i = 0; i < els.length && out.length < maxElements; i++) {
  const el = els[i];
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const visible = style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
  const tag = el.tagName.toLowerCase();
  if (tag === "input" && (el.getAttribute("type") || "") === "hidden") continue;
  const fp = { index: out.length, tag: tag, visible: visible };
  const set = (k, v) => { const c = clean(v); if (c) fp[k] = c.slice(0, 120); };
  set("role", implicitRole(el));
  set("name", accName(el));
  set("text", tag === "input" ? "" : (el.innerText != null ? el.innerText : el.textContent));
  set("id", el.getAttribute("id"));
  set("nameAttr", el.getAttribute("name"));
  for (const a of ["data-testid", "data-test", "data-qa"]) {
    if (el.getAttribute(a)) { set("testId", el.getAttribute(a)); fp.testIdAttr = a; break; }
  }
  set("type", el.getAttribute("type"));
  set("placeholder", el.getAttribute("placeholder"));
  set("label", ["input", "select", "textarea"].includes(tag) ? labelFor(el) : "");
  set("classes", el.getAttribute("class"));
  set("href", el.getAttribute("href"));
  set("ariaLabel", el.getAttribute("aria-label"));
  if (el.hasAttribute("data-qa-mcp-probe")) fp.probe = true;
  out.push(fp);
}
return out;
"""

Fingerprint = dict[str, Any]
INTERACTIVE = {"button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox", "listbox",
               "spinbutton", "slider", "tab", "menuitem", "switch", "option"}
TEXT_TAGS = {"button", "a", "h1", "h2", "h3", "h4", "label", "summary", "option", "li", "span", "div", "p", "td", "th"}
INTERNAL = ("index", "visible", "probe", "testIdAttr", "ariaLabel")


def fingerprint_page(driver, max_elements: int = 150) -> list[Fingerprint]:
    return driver.execute_script(COLLECT_JS, max_elements) or []


def fingerprint_of(driver, element) -> Fingerprint | None:
    """Fingerprint of one element (used for baselines)."""
    driver.execute_script("arguments[0].setAttribute('data-qa-mcp-probe', '1')", element)
    try:
        fp = next((f for f in fingerprint_page(driver, 2000) if f.get("probe")), None)
        if not fp:
            return None
        return {k: v for k, v in fp.items() if k not in INTERNAL}
    finally:
        try:
            driver.execute_script("arguments[0].removeAttribute('data-qa-mcp-probe')", element)
        except Exception:  # noqa: BLE001
            pass


def candidates(fp: Fingerprint) -> list[Loc]:
    """Candidate locators for one element, most stable first (not yet verified)."""
    out: list[tuple[int, Loc]] = []
    tag = fp.get("tag", "*")
    if fp.get("testId"):
        out.append((PRIORITY["testid"], Loc("css selector", f'[{fp.get("testIdAttr", "data-testid")}={css_attr(fp["testId"])}]')))
    if stable_id(fp.get("id")):
        out.append((PRIORITY["id"], Loc("id", fp["id"])))
    if fp.get("nameAttr"):
        out.append((PRIORITY["name"], Loc("name", fp["nameAttr"])))
    if tag == "a" and fp.get("text") and len(fp["text"]) <= 60:
        out.append((PRIORITY["link"], Loc("link text", fp["text"])))
    if fp.get("ariaLabel"):
        out.append((PRIORITY["aria"], Loc("css selector", f'{tag}[aria-label={css_attr(fp["ariaLabel"])}]')))
    text = fp.get("text") or (fp.get("name") if tag == "input" and fp.get("type") in ("submit", "button") else None)
    if text and len(text) <= 60 and tag in TEXT_TAGS:
        lit = xpath_lit(text)
        if lit:
            out.append((PRIORITY["text"], Loc("xpath", f"//{tag}[normalize-space()={lit}]")))
    if fp.get("placeholder"):
        out.append((PRIORITY["placeholder"], Loc("css selector", f'{tag}[placeholder={css_attr(fp["placeholder"])}]')))
    if fp.get("label") and tag in ("input", "select", "textarea") and not stable_id(fp.get("id")):
        lit = xpath_lit(fp["label"])
        if lit:
            out.append((PRIORITY["placeholder"] + 1, Loc("xpath", f"//label[normalize-space()={lit}]//{tag}")))
    return [loc for _, loc in sorted(out, key=lambda x: x[0])]


def unique_locators(driver, fp: Fingerprint) -> list[str]:
    """Rendered candidates that match exactly one element on the live page."""
    return [render(loc) for loc in candidates(fp) if count_matches(driver, loc) == 1]


def explore(driver, max_elements: int = 80, only_interactive: bool = False) -> list[dict[str, Any]]:
    fps = [f for f in fingerprint_page(driver, max_elements * 2) if f.get("visible")]
    if only_interactive:
        fps = [f for f in fps if f.get("role") in INTERACTIVE or f.get("tag") in ("input", "select", "textarea")]
    out = []
    for fp in fps[:max_elements]:
        uniq = unique_locators(driver, fp)
        el = {k: v for k, v in fp.items() if k not in ("probe", "testIdAttr", "ariaLabel", "visible")}
        el["best"] = uniq[0] if uniq else None
        el["alternatives"] = uniq[1:]
        out.append(el)
    return out
