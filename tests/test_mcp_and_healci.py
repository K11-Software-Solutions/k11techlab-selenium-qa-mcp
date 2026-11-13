"""MCP protocol round trip, the pytest runner, and heal-ci end to end."""

import json
import shutil
from pathlib import Path

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from conftest import LOGIN_STEPS
from k11_selenium_qa.healci import heal_ci
from k11_selenium_qa.runner import run_tests
from k11_selenium_qa.server import create_server

FIXTURE = Path(__file__).parent / "fixtures" / "heal-project"


def _text(result):
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


def test_mcp_tools_over_protocol(demo, tmp_path, monkeypatch, creds):
    monkeypatch.setenv("QA_MCP_ROOT", str(tmp_path))

    async def go():
        async with create_connected_server_and_client_session(create_server()._mcp_server) as client:
            from k11_selenium_qa import VERSION

            info = await client.initialize()
            assert (info.serverInfo.name, info.serverInfo.version) == ("k11-selenium-qa", VERSION)
            tools = sorted(t.name for t in (await client.list_tools()).tools)
            assert tools == ["capture_baseline", "check_locator", "explore_page", "heal_locator", "parse_user_story",
                             "run_tests", "save_login_state", "write_test"]
            assert "story_to_selenium" in [p.name for p in (await client.list_prompts()).prompts]

            story = _text(await client.call_tool("parse_user_story", {"story": "As a shopper, I want to sign in.\n- Valid login shows my name", "url": demo.url}))
            assert "def test_valid_login_shows_my_name" in story["skeleton"] and "conftest" in story
            w = _text(await client.call_tool("write_test", {"path": "test_login.py", "code": story["skeleton"]}))
            assert w["written"] == "tests/test_login.py"
            assert (await client.call_tool("write_test", {"path": "test_login.py", "code": "x"})).isError
            assert (await client.call_tool("write_test", {"path": "../../evil_test.py", "code": "x"})).isError
            assert (await client.call_tool("write_test", {"path": "notes.txt", "code": "x"})).isError

            saved = _text(await client.call_tool("save_login_state", {"url": demo.url + "/login.html", "steps": LOGIN_STEPS[:3], "success_locator": '(By.TAG_NAME, "h1")'}))
            assert saved["saved"] == ".qa-mcp/auth/default.json"
            assert "correct-horse" not in json.dumps(saved)
            assert ".qa-mcp/auth/" in (tmp_path / ".gitignore").read_text()
            session = {"storage_state": saved["saved"]}

            cap = _text(await client.call_tool("capture_baseline", {"url": demo.url + "/account.html", "session": session,
                                                                     "locators": ['(By.ID, "view-orders")', '(By.ID, "nope")']}))
            assert cap["captured"] == ['(By.ID, "view-orders")'] and "0 elements" in cap["skipped"][0]["reason"]

            demo.set_version("v2")
            healed = _text(await client.call_tool("heal_locator", {"url": demo.url + "/account.html", "locator": 'driver.find_element(By.ID, "view-orders")', "session": session}))
            assert healed["status"] == "healed" and healed["referenceSource"] == "baseline"
            assert healed["suggestion"] == '(By.ID, "orders-toggle")'
            check = _text(await client.call_tool("check_locator", {"url": demo.url + "/account.html", "locator": healed["suggestion"], "session": session}))
            assert check["verdict"] == "unique"
            explored = _text(await client.call_tool("explore_page", {"url": demo.url + "/account.html", "session": session}))
            assert any(e.get("best") == '(By.LINK_TEXT, "Account settings")' for e in explored["elements"])

    anyio.run(go)


@pytest.fixture
def project(tmp_path, demo, creds, monkeypatch):
    dest = tmp_path / "proj"
    shutil.copytree(FIXTURE, dest)
    monkeypatch.setenv("DEMO_URL", demo.url)
    return dest


def test_runner_reports_locator_and_page(project, demo):
    demo.set_version("v2")
    r = run_tests(project)
    assert r["total"] == 4 and r["failed"] == 4, r
    by = {t["name"]: t for t in r["tests"]}
    t = by["test_shows_my_orders"]
    assert t["failingLocator"] == '(By.ID, "view-orders")'
    assert t["page"].endswith("/account.html")
    assert by["test_opens_the_profile_editor"]["failingLocator"] == '(By.LINK_TEXT, "Edit profile")'
    assert "failingLocator" not in by["test_has_the_account_title"]


def test_heal_ci_end_to_end(project, demo):
    # Baselines while v1 passes, as a team would commit them.
    from k11_selenium_qa.browser import open_page
    from k11_selenium_qa.snapshot import fingerprint_of
    from k11_selenium_qa.store import BaselineStore

    assert run_tests(project)["passed"] == 4
    with open_page(demo.url + "/account.html", project, {"steps": LOGIN_STEPS}) as v:
        entries = {}
        for loc in ['(By.ID, "view-orders")', '(By.ID, "cart-btn")', '(By.LINK_TEXT, "Edit profile")']:
            from k11_selenium_qa.locators import parse_locator
            l = parse_locator(loc)
            entries[loc] = fingerprint_of(v.driver, v.driver.find_element(l.by, l.value))
        BaselineStore(project).put(v.final_url, entries)

    demo.set_version("v2")
    page_object = project / "tests" / "pages" / "account_page.py"
    before = page_object.read_bytes()

    dry = heal_ci(project, apply=False)["report"]
    assert dry["counts"]["suggested"] == 2 and page_object.read_bytes() == before

    res = heal_ci(project, apply=True)
    rep = res["report"]
    items = {i["test"].split("::")[-1]: i for i in rep["items"]}
    orders = items["test_shows_my_orders"]
    assert orders["outcome"] == "applied" and orders["verified"] is True
    assert orders["suggestion"] == '(By.ID, "orders-toggle")'
    assert orders["replacements"][0]["file"] == "tests/pages/account_page.py"
    assert items["test_shows_an_empty_cart"]["outcome"] == "reverted"
    assert items["test_opens_the_profile_editor"]["outcome"] == "needs_review"
    assert [f["test"].split("::")[-1] for f in rep["otherFailures"]] == ["test_has_the_account_title"]

    src = page_object.read_text("utf8")
    assert 'VIEW_ORDERS = (By.ID, "orders-toggle")' in src
    assert 'OPEN_CART = (By.ID, "cart-btn")' in src  # reverted
    assert page_object.read_bytes().count(b"\r\n") == before.count(b"\r\n")  # line endings kept
    md = Path(res["markdownPath"]).read_text("utf8")
    assert "**1 healed and verified**" in md and "1 reverted" in md
    assert "returns-toggle" in md  # the runner-up is part of the evidence
    (Path(__file__).parent.parent / ".tmp-last-report.md").write_text(md, "utf8")
