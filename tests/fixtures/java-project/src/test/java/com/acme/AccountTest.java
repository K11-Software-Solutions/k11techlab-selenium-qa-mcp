package com.acme;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.acme.pages.AccountPage;
import java.time.Duration;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.openqa.selenium.By;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.chrome.ChromeDriver;
import org.openqa.selenium.chrome.ChromeOptions;
import org.openqa.selenium.support.ui.ExpectedConditions;
import org.openqa.selenium.support.ui.WebDriverWait;

class AccountTest {
    private static final String BASE_URL = System.getenv().getOrDefault("DEMO_URL", "http://127.0.0.1:8765");
    private WebDriver driver;

    @BeforeEach
    void signIn() {
        ChromeOptions options = new ChromeOptions();
        options.addArguments("--headless=new", "--window-size=1280,900");
        if (System.getenv("CI") != null) options.addArguments("--no-sandbox", "--disable-dev-shm-usage");
        driver = new ChromeDriver(options);
        driver.get(BASE_URL + "/login.html");
        driver.findElement(By.id("email")).sendKeys(System.getenv().getOrDefault("APP_USER", ""));
        driver.findElement(By.id("password")).sendKeys(System.getenv().getOrDefault("APP_PASSWORD", ""));
        driver.findElement(By.xpath("//button[normalize-space()=\"Sign in\"]")).click();
        new WebDriverWait(driver, Duration.ofSeconds(10)).until(ExpectedConditions.urlContains("account.html"));
    }

    @AfterEach
    void quit() {
        if (driver != null) driver.quit();
    }

    @Test
    void showsMyOrders() {
        new AccountPage(driver).viewOrders();
        new WebDriverWait(driver, Duration.ofSeconds(5)).until(ExpectedConditions.visibilityOfElementLocated(AccountPage.ORDER_LIST));
    }

    @Test
    void opensTheProfileEditor() {
        new WebDriverWait(driver, Duration.ofSeconds(3)).until(ExpectedConditions.elementToBeClickable(By.linkText("Edit profile"))).click();
        assertTrue(driver.getCurrentUrl().endsWith("#profile"));
    }

    @Test
    void showsAnEmptyCart() {
        new AccountPage(driver).openCart();
        String message = new WebDriverWait(driver, Duration.ofSeconds(5))
            .until(ExpectedConditions.visibilityOfElementLocated(AccountPage.CART_MESSAGE)).getText();
        assertEquals("Your cart is empty", message);
    }

    @Test
    void hasTheAccountTitle() {
        assertEquals("Acme – My account", driver.getTitle());
    }
}
