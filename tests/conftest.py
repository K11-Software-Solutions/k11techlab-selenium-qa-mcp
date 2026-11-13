import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))

from server import DemoServer  # noqa: E402


@pytest.fixture
def demo():
    s = DemoServer(0, "v1").start()
    yield s
    s.close()


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("APP_USER", "alex@example.com")
    monkeypatch.setenv("APP_PASSWORD", "correct-horse")


LOGIN_STEPS = [
    {"action": "fill", "locator": '(By.ID, "email")', "value": "${ENV:APP_USER}"},
    {"action": "fill", "locator": '(By.ID, "password")', "value": "${ENV:APP_PASSWORD}"},
    {"action": "click", "locator": "(By.XPATH, '//button[normalize-space()=\"Sign in\"]')"},
    {"action": "wait_for", "locator": '(By.TAG_NAME, "h1")'},
]
