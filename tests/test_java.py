"""Java support: locator parsing, source rewriting, scaffolding, and Maven + heal-ci end to end."""

import shutil
from pathlib import Path

import pytest

from conftest import LOGIN_STEPS
from k11_selenium_qa.javarunner import failing_locator
from k11_selenium_qa.locators import Loc, parse_locator, render
from k11_selenium_qa.rewrite import replace_locator
from k11_selenium_qa.story import parse_story, scaffold_java

FIXTURE = Path(__file__).parent / "fixtures" / "java-project"
HAVE_MAVEN = shutil.which("mvn") is not None


@pytest.mark.parametrize("text,expected", [
    ('By.id("view-orders")', Loc("id", "view-orders")),
    ('driver.findElement(By.cssSelector("button.primary"))', Loc("css selector", "button.primary")),
    ('By.cssSelector("#cart-btn")', Loc("id", "cart-btn")),
    ('By.xpath("//a[text()=\\"Help\\"]")', Loc("xpath", '//a[text()="Help"]')),
    ('@FindBy(id = "view-orders")', Loc("id", "view-orders")),
    ('@FindBy(how = How.LINK_TEXT, using = "Edit profile")', Loc("link text", "Edit profile")),
    ("By.linkText: Edit profile", Loc("link text", "Edit profile")),
    ('{"method":"css selector","selector":"#view\\\\-orders"}', Loc("id", "view-orders")),
])
def test_parse_java_locators(text, expected):
    assert parse_locator(text) == expected


def test_render_java():
    assert render(Loc("id", "a"), "java") == 'By.id("a")'
    assert render(Loc("xpath", '//button[normalize-space()="Log in"]'), "java") == 'By.xpath("//button[normalize-space()=\\"Log in\\"]")'
    assert parse_locator(render(Loc("link text", "Say \"hi\""), "java")) == Loc("link text", 'Say "hi"')


def test_failing_locator_from_selenium_java_messages():
    timeout = ("Expected condition failed: waiting for element found by By.linkText: Edit profile to be clickable, "
               "but the element was not found (tried for 3 second(s) with 500 milliseconds interval)")
    assert failing_locator(timeout) == '(By.LINK_TEXT, "Edit profile")'
    visibility = "Expected condition failed: waiting for visibility of element located by By.id: view-orders (tried for 5 second(s)"
    assert failing_locator(visibility) == '(By.ID, "view-orders")'
    nse = 'no such element: Unable to locate element: {"method":"css selector","selector":"#cart\\-btn"}\n  (Session info: chrome=132)'
    assert failing_locator(nse) == '(By.ID, "cart-btn")'


def test_rewrite_java_calls_and_findby():
    src = (
        "class P {\n"
        "  // By.id(\"go\") in a comment stays\n"
        "  @FindBy(id = \"go\") WebElement go;\n"
        "  @FindBy(how = How.ID, using = \"go\") WebElement go2;\n"
        "  By b = By.id(\"go\");\n"
        "  By c = By.cssSelector(\"#go\");\n"
        "  By other = By.id(\"stay\");\n"
        "}\n"
    )
    out, reps = replace_locator(src, Loc("id", "go"), Loc("xpath", '//button[normalize-space()="Go"]'), "P.java")
    assert [r.line for r in reps] == [3, 4, 5, 6]
    assert '@FindBy(xpath = "//button[normalize-space()=\\"Go\\"]") WebElement go;' in out
    assert 'By b = By.xpath("//button[normalize-space()=\\"Go\\"]");' in out
    assert '// By.id("go") in a comment stays' in out and 'By.id("stay")' in out


def test_scaffold_java():
    story = parse_story("As a shopper, I want to sign in.\n- Valid login shows my name\n- Wrong password shows an error")
    junit = scaffold_java(story, "http://x/login", "com.acme.tests")
    assert junit.startswith("package com.acme.tests;")
    assert "class SignInTest {" in junit and "void validLoginShowsMyName()" in junit
    assert "@DisplayName(\"Wrong password shows an error\")" in junit
    testng = scaffold_java(story, None, None, "testng")
    assert "import org.testng.annotations.Test;" in testng and "public class SignInTest {" in testng
    assert junit.count("{") == junit.count("}")


@pytest.fixture
def java_project(tmp_path, demo, creds, monkeypatch):
    dest = tmp_path / "jproj"
    shutil.copytree(FIXTURE, dest, ignore=shutil.ignore_patterns("target"))
    monkeypatch.setenv("DEMO_URL", demo.url)
    return dest


@pytest.mark.skipif(not HAVE_MAVEN, reason="Maven not installed")
def test_java_heal_ci_end_to_end(java_project, demo):
    from k11_selenium_qa.browser import open_page
    from k11_selenium_qa.healci import heal_ci
    from k11_selenium_qa.runner import run_tests
    from k11_selenium_qa.snapshot import fingerprint_of
    from k11_selenium_qa.store import BaselineStore

    first = run_tests(java_project)
    assert first.get("passed") == 4, first

    # Baselines while v1 passes (keys are the canonical form; the page is how Java runs find it).
    with open_page(demo.url + "/account.html", java_project, {"steps": LOGIN_STEPS}) as v:
        entries = {}
        for loc in (Loc("id", "view-orders"), Loc("id", "cart-btn"), Loc("link text", "Edit profile")):
            entries[render(loc)] = fingerprint_of(v.driver, v.driver.find_element(loc.by, loc.value))
        BaselineStore(java_project).put(v.final_url, entries)

    demo.set_version("v2")
    page_object = java_project / "src/test/java/com/acme/pages/AccountPage.java"
    before = page_object.read_bytes()
    res = heal_ci(java_project, apply=True)
    rep = res["report"]
    items = {i["test"].split("#")[-1]: i for i in rep["items"]}

    orders = items["showsMyOrders"]
    assert orders["outcome"] == "applied" and orders["verified"] is True, orders
    assert orders["locator"] == 'By.id("view-orders")'
    assert orders["suggestion"] == 'By.id("orders-toggle")'
    assert orders["replacements"][0]["file"] == "src/test/java/com/acme/pages/AccountPage.java"
    assert orders["replacements"][0]["before"] == '@FindBy(id = "view-orders")'
    assert items["showsAnEmptyCart"]["outcome"] == "reverted"
    assert items["opensTheProfileEditor"]["outcome"] == "needs_review"
    assert [f["test"].split("#")[-1] for f in rep["otherFailures"]] == ["hasTheAccountTitle"]

    src = page_object.read_text("utf8")
    assert '@FindBy(id = "orders-toggle")' in src
    assert '@FindBy(how = org.openqa.selenium.support.How.ID, using = "cart-btn")' in src  # reverted
    assert page_object.read_bytes().count(b"\r\n") == before.count(b"\r\n")
    md = Path(res["markdownPath"]).read_text("utf8")
    assert "**1 healed and verified**" in md and 'By.id("returns-toggle")' in md
    (Path(__file__).parent.parent / ".tmp-last-java-report.md").write_text(md, "utf8")


def test_mcp_tools_speak_java(demo, tmp_path, monkeypatch, creds):
    import json

    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    from k11_selenium_qa.server import create_server

    (tmp_path / "pom.xml").write_text("<project><artifactId>x</artifactId></project>")
    monkeypatch.setenv("QA_MCP_ROOT", str(tmp_path))

    async def go():
        async with create_connected_server_and_client_session(create_server()._mcp_server) as client:
            def text(r):
                assert not r.isError, r.content[0].text
                return json.loads(r.content[0].text)

            explored = text(await client.call_tool("explore_page", {"url": demo.url + "/store/login.html"}))
            best = {e.get("name"): e["best"] for e in explored["elements"]}
            assert best["Sign in"] == 'By.id("login-btn")'
            story = text(await client.call_tool("parse_user_story", {"story": "As a user, I want to sign in.\n- Valid login works",
                                                                      "package": "com.acme", "class_name": "LoginTest"}))
            assert story["language"] == "java" and "class LoginTest {" in story["skeleton"]
            w = text(await client.call_tool("write_test", {"path": "com/acme/LoginTest.java", "code": story["skeleton"]}))
            assert w["written"] == "src/test/java/com/acme/LoginTest.java"
            assert (await client.call_tool("write_test", {"path": "com/acme/notes.txt", "code": "x"})).isError
            assert (await client.call_tool("write_test", {"path": "../../main/java/Evil.java", "code": "x"})).isError
            assert (await client.call_tool("run_tests", {"target": "Login;calc"})).isError
            healed = text(await client.call_tool("heal_locator", {"url": demo.url + "/store/login.html",
                                                                  "locator": '@FindBy(xpath = "//button[normalize-space()=\\"Log in\\"]")'}))
            assert healed["original"] == 'By.xpath("//button[normalize-space()=\\"Log in\\"]")'
            assert healed["candidates"][0]["locator"] == 'By.id("login-btn")'

    anyio.run(go)
