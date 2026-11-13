from selenium.webdriver.common.by import By


class AccountPage:
    """Page Object for the account page. heal-ci edits locators here too."""

    VIEW_ORDERS = (By.ID, "view-orders")
    ORDER_LIST = (By.XPATH, "//li[contains(., 'Order #1001')]")
    OPEN_CART = (By.ID, "cart-btn")
    CART_MESSAGE = (By.CSS_SELECTOR, "p.panel")
