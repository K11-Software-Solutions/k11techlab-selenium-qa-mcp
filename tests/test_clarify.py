"""review_user_story: the questions a careful tester asks before any test is written.

The cases live in tests/fixtures/review_cases.json, shared with k11 Playwright QA: both
implementations must produce exactly the same questions for the same story, so the rules can't
drift apart between the two tools.
"""
import json
from pathlib import Path

import pytest

from k11_selenium_qa.clarify import review_story
from k11_selenium_qa.story import parse_story

CASES = json.loads((Path(__file__).parent / "fixtures" / "review_cases.json").read_text(encoding="utf-8"))["cases"]


def review(raw, context=None):
    return review_story(parse_story(raw), raw, context)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_matches_the_shared_cases(case):
    r = review(case["story"], case.get("context"))
    got = [{k: q[k] for k in ("kind", "question", "quote") if k in q} for q in r["questions"]]
    assert {"ready": r["ready"], "questions": got} == case["expect"]


def test_the_shared_cases_cover_every_kind_and_both_directions():
    kinds = {q["kind"] for c in CASES for q in c["expect"]["questions"]}
    assert kinds == {"criteria", "role", "vague-term", "outcome", "precondition", "limit", "failure-path", "undefined-term"}
    assert sum(c["expect"]["ready"] for c in CASES) >= 3          # negative controls: stories that must get no questions


def test_every_question_says_why():
    qs = review("I want the search to be fast and easy to use, with several filters as needed.")["questions"]
    assert len(qs) > 3 and all(len(q["why"]) > 20 for q in qs)


def test_is_deterministic():
    raw = "I want the search to be fast and easy to use."
    assert review(raw) == review(raw)


def test_no_context_no_undefined_term_questions():
    raw = next(c for c in CASES if c.get("context"))["story"]
    assert not any(q["kind"] == "undefined-term" for q in review(raw)["questions"])


def test_assumptions_name_the_role():
    assert review("As an admin, I want x.\n- I see x")["assumptions"][0] == "The tests will use a admin account."
    assert review("I want x.")["assumptions"][0] == "The tests will use a standard signed-in user."
