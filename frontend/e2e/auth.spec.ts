import { test, expect } from "@playwright/test";

/**
 * Happy-path: logowanie → lista portfeli → wylogowanie. Przygotowuje
 * użytkownika testowego bezpośrednio przez API (szybciej i stabilniej niż
 * przez formularz rejestracji, który ma swój osobny test niżej).
 */
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000/api";

function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@alphasense.example`;
}

test.describe("mobile 375px — brak poziomego scrolla", () => {
  for (const path of ["/login", "/register"]) {
    test(`${path} nie ma poziomego scrolla`, async ({ page }) => {
      await page.goto(path);
      const { scrollWidth, clientWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
    });
  }
});

test("login → lista portfeli → logout", async ({ page, request }) => {
  const email = uniqueEmail("e2e-login");
  const password = "TestPass123";

  const registerResponse = await request.post(`${API_URL}/auth/register`, {
    data: { email, password },
  });
  expect(registerResponse.ok()).toBeTruthy();

  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Hasło").fill(password);
  await page.getByRole("button", { name: "Zaloguj się" }).click();

  await expect(page).toHaveURL(/\/portfolios$/);
  await expect(page.getByRole("heading", { name: "Twoje portfele" })).toBeVisible();

  // Nawigacja pokazuje "Wyloguj" zamiast "Zaloguj się" po zalogowaniu.
  const logoutButtons = page.getByRole("button", { name: "Wyloguj" });
  await expect(logoutButtons.first()).toBeVisible();

  // F5 nie wylogowuje — silent refresh po stronie serwera odzyskuje sesję.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Twoje portfele" })).toBeVisible();

  await logoutButtons.first().click();
  await expect(page).toHaveURL(/\/login$/);

  // Po wylogowaniu /portfolios znów przekierowuje na /login.
  await page.goto("/portfolios");
  await expect(page).toHaveURL(/\/login$/);
});

test("rejestracja → automatyczne logowanie → lista portfeli", async ({ page }) => {
  const email = uniqueEmail("e2e-register");
  const password = "TestPass123";

  await page.goto("/register");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Hasło").fill(password);
  await page.getByRole("button", { name: "Załóż konto" }).click();

  await expect(page).toHaveURL(/\/portfolios$/);
  await expect(page.getByRole("heading", { name: "Twoje portfele" })).toBeVisible();
});
