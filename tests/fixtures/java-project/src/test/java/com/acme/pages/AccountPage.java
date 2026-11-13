package com.acme.pages;

import org.openqa.selenium.By;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;
import org.openqa.selenium.support.PageFactory;

/** Page Object for the account page. heal-ci edits locators here too. */
public class AccountPage {
    public static final By ORDER_LIST = By.xpath("//li[contains(., 'Order #1001')]");
    public static final By CART_MESSAGE = By.cssSelector("p.panel");

    @FindBy(id = "view-orders")
    private WebElement viewOrders;

    @FindBy(how = org.openqa.selenium.support.How.ID, using = "cart-btn")
    private WebElement openCart;

    public AccountPage(WebDriver driver) {
        PageFactory.initElements(driver, this);
    }

    public void viewOrders() {
        viewOrders.click();
    }

    public void openCart() {
        openCart.click();
    }
}
