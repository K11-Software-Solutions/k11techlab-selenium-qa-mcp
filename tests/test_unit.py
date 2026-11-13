import pytest

from k11_selenium_qa.heal import score, text_similarity
from k11_selenium_qa.locators import Loc, implied_fingerprint, parse_locator, render
from k11_selenium_qa.rewrite import replace_locator
from k11_selenium_qa.session import describe_step, resolve_env, resolve_storage_state, validate_steps
from k11_selenium_qa.snapshot import candidates
from k11_selenium_qa.story import parse_story, scaffold_test


@pytest.mark.parametrize("text,expected", [
    ('(By.ID, "login-btn")', Loc("id", "login-btn")),
    ("By.CSS_SELECTOR, '.btn.primary'", Loc("css selector", ".btn.primary")),
    ('driver.find_element(By.XPATH, "//button[text()=\'Go\']")', Loc("xpath", "//button[text()='Go']")),
    ('wait.until(EC.visibility_of_element_located((By.NAME, "q")))', Loc("name", "q")),
    ('find_element("link text", "Help")', Loc("link text", "Help")),
    ('{"method":"css selector","selector":"[id=\\"view-orders\\"]"}', Loc("id", "view-orders")),
    ('(By.CSS_SELECTOR, \'[name="email"]\')', Loc("name", "email")),
])
def test_parse_locator(text, expected):
    assert parse_locator(text) == expected


@pytest.mark.parametrize("text", ["By.ID", "__import__('os').system('x')", "(By.FOO, 'x')", "(By.ID, x)", "(By.ID, '')"])
def test_parse_locator_rejects(text):
    assert parse_locator(text) is None


def test_render_roundtrip():
    for loc in [Loc("id", "a"), Loc("xpath", '//a[normalize-space()="Say \'hi\'"]'), Loc("css selector", '[data-testid="x"]')]:
        assert parse_locator(render(loc)) == loc


def test_implied_fingerprint():
    assert implied_fingerprint(Loc("id", "login-btn")) == {"id": "login-btn"}
    assert implied_fingerprint(Loc("xpath", '//button[normalize-space()="Sign in"]')) == {"tag": "button", "name": "Sign in"}
    assert implied_fingerprint(Loc("css selector", "button.btn.primary"))["classes"] == "btn primary"
    assert implied_fingerprint(Loc("link text", "Help")) == {"role": "link", "name": "Help"}


def test_similarity_and_scoring():
    assert text_similarity("Sign in", "Log in") >= 0.99
    assert text_similarity("login-btn", "signin-submit") > 0.3
    s, reasons = score({"name": "Sign in", "tag": "button"}, {"name": "Log in", "tag": "button", "visible": True})
    assert s > 0.95 and any("equivalent" in r for r in reasons)


def test_candidates_order():
    fp = {"tag": "button", "id": "save", "text": "Save", "name": "Save", "testId": "save-btn", "testIdAttr": "data-testid"}
    locs = [render(c) for c in candidates(fp)]
    assert locs[0] == '(By.CSS_SELECTOR, \'[data-testid="save-btn"]\')'
    assert locs[1] == '(By.ID, "save")'
    assert '(By.XPATH, \'//button[normalize-space()="Save"]\')' in locs
    assert all("ember" not in l for l in [render(c) for c in candidates({"tag": "div", "id": "ember123"})])


def test_story_and_scaffold():
    story = parse_story("As a shopper, I want to sign in so that I can see my orders.\n- Valid login shows my name\n- Wrong password shows an error")
    assert story["role"] == "shopper" and len(story["scenarios"]) == 2
    code = scaffold_test(story, "http://x/login")
    compile(code, "t.py", "exec")
    assert "def test_valid_login_shows_my_name(self, driver):" in code
    gherkin = parse_story("Scenario: Login\nGiven I am on the login page\nWhen I sign in\nThen I see my name")
    assert [s["keyword"] for s in gherkin["scenarios"][0]["steps"]] == ["Given", "When", "Then"]


def test_rewrite_python_source():
    src = (
        "from selenium.webdriver.common.by import By\n"
        "class P:\n"
        '    LOGIN = (By.ID, "login-btn")  # (By.ID, "login-btn") in a comment stays\n'
        "def t(d):\n"
        "    d.find_element(By.ID, 'login-btn').click()\n"
        '    d.find_element(By.ID, "other")\n'
    )
    out, reps = replace_locator(src, Loc("id", "login-btn"), Loc("xpath", '//button[normalize-space()="Log in"]'))
    assert [r.line for r in reps] == [3, 5]
    assert "LOGIN = (By.XPATH, '//button[normalize-space()=\"Log in\"]')" in out
    assert '# (By.ID, "login-btn") in a comment stays' in out
    assert 'By.ID, "other"' in out
    compile(out, "x.py", "exec")


def test_sessions_validate_and_mask(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="Step 1 \\(click\\): needs locator"):
        validate_steps([{"action": "click"}])
    with pytest.raises(ValueError, match="unsupported locator"):
        validate_steps([{"action": "click", "locator": "os.system('x')"}])
    with pytest.raises(ValueError, match="needs value"):
        validate_steps([{"action": "fill", "locator": '(By.ID, "a")'}])
    assert describe_step({"action": "fill", "locator": '(By.ID, "pw")', "value": "hunter2"}).endswith("•••")
    assert describe_step({"action": "fill", "locator": '(By.ID, "pw")', "value": "${ENV:PW}"}).endswith("${ENV:PW}")
    monkeypatch.setenv("PW", "s3cret")
    assert resolve_env("${ENV:PW}") == "s3cret"
    with pytest.raises(ValueError, match="NOPE_X is not set"):
        resolve_env("${ENV:NOPE_X}")
    with pytest.raises(ValueError, match="inside the project"):
        resolve_storage_state(tmp_path, "../outside.json")
