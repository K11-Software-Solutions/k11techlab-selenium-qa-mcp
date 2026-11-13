from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from pages.account_page import AccountPage


class TestAccount:
    def test_shows_my_orders(self, signed_in):
        signed_in.find_element(*AccountPage.VIEW_ORDERS).click()
        WebDriverWait(signed_in, 5).until(EC.visibility_of_element_located(AccountPage.ORDER_LIST))

    def test_opens_the_profile_editor(self, signed_in):
        WebDriverWait(signed_in, 3).until(EC.element_to_be_clickable((By.LINK_TEXT, "Edit profile"))).click()
        assert signed_in.current_url.endswith("#profile")

    def test_shows_an_empty_cart(self, signed_in):
        signed_in.find_element(*AccountPage.OPEN_CART).click()
        message = WebDriverWait(signed_in, 5).until(EC.visibility_of_element_located(AccountPage.CART_MESSAGE))
        assert message.text == "Your cart is empty"

    def test_has_the_account_title(self, signed_in):
        assert signed_in.title == "Acme – My account"
