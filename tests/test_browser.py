"""Real-browser tests: exploration, healing and sessions against the demo app."""

import pytest

from conftest import LOGIN_STEPS
from k11_selenium_qa.browser import open_page
from k11_selenium_qa.heal import heal
from k11_selenium_qa.locators import Loc, parse_locator, render
from k11_selenium_qa.session import capture_storage_state
from k11_selenium_qa.snapshot import explore, fingerprint_of


def test_explore_returns_unique_locators(demo, tmp_path):
    with open_page(demo.url + "/store/login.html", tmp_path) as v:
        els = explore(v.driver, 40, True)
        by_name = {e.get("name"): e for e in els}
        assert by_name["Sign in"]["best"] == '(By.ID, "login-btn")'
        assert by_name["Email address"]["best"] == '(By.ID, "email")'
        for e in els:
            if e["best"]:
                loc = parse_locator(e["best"])
                assert len(v.driver.find_elements(loc.by, loc.value)) == 1


def test_heal_after_redesign_with_baseline(demo, tmp_path):
    broken = Loc("id", "login-btn")
    with open_page(demo.url + "/store/login.html", tmp_path) as v:
        baseline = fingerprint_of(v.driver, v.driver.find_element(broken.by, broken.value))
    demo.set_version("v2")
    with open_page(demo.url + "/store/login.html", tmp_path) as v:
        r = heal(v.driver, broken, render(broken), baseline)
    assert r["status"] == "healed", r
    assert r["suggestion"] == '(By.ID, "signin-submit")'
    assert r["confidence"] >= 0.8
    assert any("equivalent" in x for x in r["reasons"])
    assert "Google" in str(r["candidates"][1]["locator"]) or r["candidates"][1]["score"] < r["confidence"] - 0.1


def test_heal_without_baseline_uses_implied(demo, tmp_path):
    demo.set_version("v2")
    loc = Loc("xpath", '//button[normalize-space()="Sign in"]')
    with open_page(demo.url + "/store/login.html", tmp_path) as v:
        r = heal(v.driver, loc, render(loc))
    assert r["referenceSource"] == "implied"
    assert r["candidates"][0]["locator"] == '(By.ID, "signin-submit")'


def test_login_steps_and_storage_state(demo, tmp_path, creds):
    with open_page(demo.url + "/account.html", tmp_path) as v:
        assert v.final_url.endswith("/login.html")  # redirected: not signed in
    with open_page(demo.url + "/account.html", tmp_path, {"steps": LOGIN_STEPS}) as v:
        assert v.final_url.endswith("/account.html")
        assert v.steps[0].endswith("${ENV:APP_USER}")
        assert all("correct-horse" not in s for s in v.steps)
        state = capture_storage_state(v.driver)
    import json

    (tmp_path / "auth.json").write_text(json.dumps(state))
    with open_page(demo.url + "/account.html", tmp_path, {"storage_state": "auth.json"}) as v:
        assert v.final_url.endswith("/account.html")


def test_failed_step_does_not_leak_secret(demo, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "hunter2")
    steps = [{"action": "fill", "locator": '(By.ID, "nope")', "value": "hunter2"}]
    with pytest.raises(RuntimeError) as e:
        with open_page(demo.url + "/login.html", tmp_path, {"steps": steps}):
            pass
    assert "Step 1 failed" in str(e.value) and "hunter2" not in str(e.value)
