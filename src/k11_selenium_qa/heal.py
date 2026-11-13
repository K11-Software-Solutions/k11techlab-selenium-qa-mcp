"""Self-healing locators.

When a locator stops matching, every element on the current page is scored against
the element's last known fingerprint (a baseline captured while the test passed, or
what the locator itself implies) and the best match gets a verified replacement.
Suggestions are never applied silently: the caller decides.
"""

from __future__ import annotations

import re
from typing import Any

from .locators import Loc, count_matches, implied_fingerprint, render
from .snapshot import Fingerprint, fingerprint_page, unique_locators

SYNONYMS = {
    "btn": "button", "pwd": "password", "passwd": "password", "pass": "password", "signin": "login",
    "logon": "login", "login": "login", "log": "login", "sign": "login", "mail": "email", "e-mail": "email",
    "usr": "user", "username": "user", "submit": "send", "qty": "quantity", "del": "delete",
    "remove": "delete", "nav": "navigation",
}


def tokens(s: str | None) -> list[str]:
    if not s:
        return []
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s).lower()
    return [SYNONYMS.get(t, t) for t in re.split(r"[^a-z0-9]+", s) if t]


def _levenshtein(a: str, b: str) -> int:
    dp = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, len(b) + 1):
            tmp = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (0 if a[i - 1] == b[j - 1] else 1))
            prev = tmp
    return dp[len(b)]


def text_similarity(a: str | None, b: str | None) -> float:
    """0..1: the better of token overlap and normalised edit distance (after synonyms)."""
    if not a or not b:
        return 0.0
    ta, tb = list(dict.fromkeys(tokens(a))), list(dict.fromkeys(tokens(b)))
    inter = len(set(ta) & set(tb))
    union = len(set(ta) | set(tb)) or 1
    x, y = " ".join(ta), " ".join(tb)
    lev = 1 - _levenshtein(x, y) / max(len(x), len(y), 1)
    return max(inter / union, lev)


WEIGHTS: list[tuple[str, float, str]] = [
    ("testId", 3, "exact"),
    ("name", 2.5, "fuzzy"),
    ("id", 2, "fuzzy"),
    ("role", 1.5, "exact"),
    ("nameAttr", 1.5, "fuzzy"),
    ("text", 1.5, "fuzzy"),
    ("label", 1.5, "fuzzy"),
    ("placeholder", 1, "fuzzy"),
    ("type", 1, "exact"),
    ("tag", 1, "exact"),
    ("classes", 1, "fuzzy"),
    ("href", 1, "fuzzy"),
]


def score(ref: dict[str, str], el: Fingerprint) -> tuple[float, list[str]]:
    total = got = 0.0
    reasons: list[str] = []
    for key, w, mode in WEIGHTS:
        r = ref.get(key)
        if not r:
            continue
        total += w
        v = el.get(key)
        if mode == "exact":
            s = 1.0 if v is not None and str(v).lower() == str(r).lower() else 0.0
        else:
            s = text_similarity(str(r), v)
        got += w * s
        if s >= 0.99:
            if v is not None and str(v).lower() != str(r).lower():
                reasons.append(f'{key} equivalent: "{r}" → "{v}"')
            else:
                reasons.append(f"{key} matches")
        elif s >= 0.4:
            reasons.append(f'{key} similar ({round(s * 100)}%): "{r}" → "{v}"')
        elif v is not None and mode == "exact":
            reasons.append(f'{key} differs: "{r}" → "{v}"')
    return (got / total if total else 0.0), reasons


def rank(ref: dict[str, str], elements: list[Fingerprint], top: int = 3) -> list[tuple[Fingerprint, float, list[str]]]:
    scored = [(e, *score(ref, e)) for e in elements if e.get("visible")]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top]


AUTO_SCORE = 0.55
AUTO_MARGIN = 0.1


def heal(driver, loc: Loc | None, original: str, baseline: dict[str, str] | None = None,
         lang: str = "python") -> dict[str, Any]:
    if loc is None:
        return {"status": "unparseable", "original": original,
                "note": 'Use a single Selenium locator such as (By.ID, "login"), By.id("login") or @FindBy(id = "login").'}
    matches = count_matches(driver, loc)
    if matches == 1:
        return {"status": "healthy", "original": render(loc, lang), "matches": 1}

    ref = baseline or implied_fingerprint(loc)
    ranked = rank(ref, fingerprint_page(driver, 400), 3)
    cands = []
    for el, sc, reasons in ranked:
        uniq = unique_locators(driver, el, lang)
        cands.append({"locator": uniq[0] if uniq else None, "score": round(sc, 2), "reasons": reasons})
    base: dict[str, Any] = {
        "status": "needs_review",
        "original": render(loc, lang),
        "matches": matches,
        "candidates": cands,
        "referenceSource": "baseline" if baseline else "implied",
    }
    best = cands[0] if cands else None
    if not best or best["score"] < 0.3:
        return {**base, "status": "not_found", "note": "No element on the page resembles the original."}
    margin = best["score"] - cands[1]["score"] if len(cands) > 1 else best["score"]
    if matches > 1:
        base["status"] = "ambiguous"
    if best["locator"] and best["score"] >= AUTO_SCORE and margin >= AUTO_MARGIN:
        return {**base, "status": "ambiguous" if matches > 1 else "healed", "suggestion": best["locator"],
                "confidence": best["score"], "reasons": best["reasons"]}
    note = ("No baseline fingerprint for this locator, so matching used only what the locator itself implies. "
            "Run capture_baseline while tests pass to make healing more reliable."
            if not baseline else "Best match is not clearly better than the alternatives; confirm before applying.")
    return {**base, "suggestion": best["locator"], "confidence": best["score"], "reasons": best["reasons"], "note": note}
