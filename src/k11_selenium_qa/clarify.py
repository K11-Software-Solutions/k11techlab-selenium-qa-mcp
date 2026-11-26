"""Review a user story before generating tests from it: what would a careful tester ask first?

Generating tests from an unclear story doesn't remove the ambiguity; it hides it inside test
code, as guesses nobody agreed to. This review finds the gaps and turns each into a question
for a person to answer, with the reason it matters and, where it applies, the exact words in
the story that raised it.

The rules are deterministic, so the same story always gets the same questions, and they can be
tested. They match k11 Playwright QA's review_user_story exactly: both repositories test against
the same cases in tests/fixtures/review_cases.json.

  outcome         a scenario has no observable result, or the result is vague ("works", "correctly")
  criteria        no acceptance criteria at all; the only "scenario" is the goal itself
  role            no user role (permissions and test accounts depend on it)
  vague-term      words a test can't check: fast, easy, many, appropriate, user-friendly...
  limit           a limit or threshold without a number ("up to", "maximum", "expires")
  failure-path    no scenario says what happens when things go wrong
  precondition    scenarios with actions but no starting state (who is signed in, what data exists)
  undefined-term  with context: a term the story relies on that the context never explains
"""

from __future__ import annotations

import re
from typing import Any, Optional

VAGUE = [
    "fast", "quickly", "quick", "slow", "easy", "easily", "simple", "simply", "intuitive", "user-friendly", "user friendly",
    "seamless", "seamlessly", "many", "several", "some", "few", "large", "small", "appropriate", "appropriately",
    "properly", "correctly", "as needed", "as expected", "efficient", "efficiently", "reasonable", "secure", "robust",
    "and/or", "etc", "usually", "normally", "relevant", "nice", "better",
]
VAGUE_OUTCOME = re.compile(r"\b(works?|working|is successful|succeeds?|correctly|properly|as expected|is handled|handles it|is fine|is ok(ay)?)\b", re.I)
OBSERVABLE = re.compile(r'\b(see|sees|shown?|shows|display(s|ed)?|visible|message|redirect(s|ed)?|page|url|receives?|email|download(s|ed)?|disabled|enabled|error|text|title|heading|count|list|button|link|status|toast|banner|notification|"[^"]+")\b', re.I)
FAILURE = re.compile(r"\b(invalid|wrong|incorrect|error|fail(s|ed|ure)?|denied|forbidden|reject(s|ed)?|refuse[sd]?|declined|disallowed|blocked|unauthori[sz]ed|expired?|empty|missing|blank|not\b|no\b|cannot|can't|unknown|locked|timeout|offline|duplicate|too (long|many|short))\b", re.I)
LIMIT = re.compile(r"\b(up to|at most|at least|maximum|minimum|max|min|limit(ed)?|expires?|timeout|within|no more than|no less than|threshold|retries|attempts)\b", re.I)
HAS_NUMBER = re.compile(r"\d")
STOP_TERMS = {"As", "I", "Given", "When", "Then", "And", "But", "Scenario", "Title", "Story", "Feature",
              "Acceptance", "AC", "The", "A", "An", "If", "So", "On", "In", "My", "Our", "This", "That", "It"}
TRAILING = re.compile(r"[,.;:!?)]+$")
CAPITALISED = re.compile(r"^[A-Z][a-zA-Z0-9-]+$")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.replace("\r", ""))
    out = [re.sub(r"^[-*•]\s*|^\d+[.)]\s*", "", p, count=1).strip() for p in parts]
    return [s for s in out if s]


def _word_re(term: str) -> re.Pattern[str]:
    return re.compile(r"(^|[^a-z])" + re.escape(term) + r"([^a-z]|$)", re.I)


def _named_terms(raw: str) -> list[str]:
    """Terms a story relies on: quoted phrases and Capitalised Multi Word names that aren't sentence starts."""
    out: dict[str, None] = {}
    for m in re.finditer(r'"([^"]{2,40})"', raw):
        out[m.group(1).strip()] = None
    for s in _sentences(raw):
        words = re.split(r"\s+", s)
        i = 1
        while i < len(words):
            run: list[str] = []
            while i < len(words) and CAPITALISED.match(TRAILING.sub("", words[i])) and words[i] not in STOP_TERMS:
                run.append(TRAILING.sub("", words[i]))
                i += 1
            if run:
                out[" ".join(run)] = None
            i += 1
    return list(out)


def review_story(story: dict[str, Any], raw: str, context: Optional[str] = None) -> dict[str, Any]:
    """story: the dict parse_story returns. Returns {ready, questions, assumptions}."""
    questions: list[dict[str, str]] = []
    scenarios = story.get("scenarios", [])
    every = _sentences(raw)
    only_goal = (len(scenarios) == 1 and len(scenarios[0]["steps"]) == 1
                 and scenarios[0]["steps"][0]["keyword"] == "Check" and scenarios[0]["steps"][0]["text"] == story.get("goal"))

    if not scenarios or only_goal:
        questions.append({
            "kind": "criteria",
            "question": "What are the acceptance criteria? List what must be true for this story to be done.",
            "why": "Without criteria, tests can only check that the page loads, and anything else they assert is a guess.",
        })
    else:
        for sc in scenarios:
            outcomes = [s for s in sc["steps"] if s["keyword"] in ("Then", "Check")]
            text = " ".join(s["text"] for s in outcomes)
            if not outcomes:
                questions.append({
                    "kind": "outcome",
                    "question": f'In "{sc["name"]}", what should the user see or what should change at the end?',
                    "why": "A scenario with no Then has nothing to assert.",
                })
            elif VAGUE_OUTCOME.search(text) and not OBSERVABLE.search(text):
                questions.append({
                    "kind": "outcome",
                    "question": f'In "{sc["name"]}", what exactly shows that it worked: a message, a page, a value, an email?',
                    "why": "\"Works\" or \"correctly\" can't be asserted; a test needs something observable.",
                    "quote": "; ".join(f'{s["keyword"]} {s["text"]}' for s in outcomes),
                })
            acts = any(s["keyword"] == "When" for s in sc["steps"])
            if acts and not any(s["keyword"] == "Given" for s in sc["steps"]):
                questions.append({
                    "kind": "precondition",
                    "question": f'In "{sc["name"]}", what is the starting state: who is signed in, and what data already exists?',
                    "why": "Tests need set-up; guessing it makes them pass for the wrong reason or fail on a clean environment.",
                })

    if not story.get("role"):
        questions.append({
            "kind": "role",
            "question": "Who is the user: a visitor, a signed-in customer, an admin? Does anyone else get different behaviour?",
            "why": "Permissions, test accounts and what the page shows all depend on the role.",
        })

    seen: set[str] = set()
    outcome_quotes = {part for q in questions if q["kind"] == "outcome" and q.get("quote") for part in q["quote"].split("; ")}
    for s in every:
        # Quoted text is what the page shows ("This code has expired"), not a requirement to question.
        req = re.sub(r'"[^"]*"', '""', s)
        for term in VAGUE:
            if s in outcome_quotes:
                continue                                   # already asked about as a vague outcome
            if _word_re(term).search(req) and term not in seen:
                seen.add(term)
                questions.append({
                    "kind": "vague-term",
                    "question": f'"{term}" can\'t be tested as written. What is the measurable version (a number, a time, a specific behaviour)?',
                    "why": "A test needs a threshold or a concrete expectation.",
                    "quote": s,
                })
        if LIMIT.search(req) and not HAS_NUMBER.search(s):
            questions.append({
                "kind": "limit",
                "question": "What is the actual number for this limit, and what happens exactly at it and one past it?",
                "why": "Boundary tests need the boundary.",
                "quote": s,
            })

    scenario_text = " ".join(f'{sc["name"]} {" ".join(s["text"] for s in sc["steps"])}' for sc in scenarios)
    if scenarios and not only_goal and not FAILURE.search(scenario_text):
        questions.append({
            "kind": "failure-path",
            "question": "What should happen when it goes wrong: invalid input, no permission, an expired session, a server error?",
            "why": "Every scenario is a success path, so failures are untested; this is where most production bugs are.",
        })

    if context:
        for term in _named_terms(raw):
            if not _word_re(term).search(context):
                questions.append({
                    "kind": "undefined-term",
                    "question": f'What does "{term}" mean here? The context provided doesn\'t mention it.',
                    "why": "The story depends on it, and a test built on a wrong reading checks the wrong thing.",
                    "quote": term,
                })

    role = story.get("role")
    assumptions = [
        f"The tests will use a {role} account." if role else "The tests will use a standard signed-in user.",
        "Anything a question above asks about will be left as a TODO, not guessed.",
    ]
    return {"ready": not questions, "questions": questions, "assumptions": assumptions}
