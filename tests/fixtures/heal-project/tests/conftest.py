import os

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = os.environ.get("DEMO_URL", "http://127.0.0.1:8765")


@pytest.fixture
def driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    if os.environ.get("CI"):
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
    drv = webdriver.Chrome(options=opts)
    yield drv
    drv.quit()


@pytest.fixture
def signed_in(driver):
    driver.get(BASE_URL + "/login.html")
    driver.find_element(By.ID, "email").send_keys(os.environ.get("APP_USER", ""))
    driver.find_element(By.ID, "password").send_keys(os.environ.get("APP_PASSWORD", ""))
    driver.find_element(By.XPATH, '//button[normalize-space()="Sign in"]').click()
    WebDriverWait(driver, 10).until(EC.url_contains("account.html"))
    return driver
