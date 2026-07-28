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

test("login → lista portfeli → logout → logowanie innego użytkownika", async ({
  page,
  request,
}) => {
  const password = "TestPass123";
  const emailA = uniqueEmail("e2e-login-a");
  const emailB = uniqueEmail("e2e-login-b");
  const portfolioNameA = `Portfel prywatny A ${Date.now()}`;

  for (const email of [emailA, emailB]) {
    const registerResponse = await request.post(`${API_URL}/auth/register`, {
      data: { email, password },
    });
    expect(registerResponse.ok()).toBeTruthy();
  }

  await page.goto("/login");
  await page.getByLabel("E-mail").fill(emailA);
  await page.getByLabel("Hasło").fill(password);
  await page.getByRole("button", { name: "Zaloguj się" }).click();

  await expect(page).toHaveURL(/\/portfolios$/);
  await expect(page.getByRole("heading", { name: "Twoje portfele" })).toBeVisible();

  // Nawigacja pokazuje "Wyloguj" zamiast "Zaloguj się" po zalogowaniu.
  const logoutButtons = page.getByRole("button", { name: "Wyloguj" });
  await expect(logoutButtons.first()).toBeVisible();

  // A tworzy portfel przez UI — dopiero to zapełnia cache TanStack Query
  // w tej karcie (przygotowanie danych przez API by go nie dotknęło).
  await page.getByLabel("Nazwa portfela").fill(portfolioNameA);
  await page.getByRole("button", { name: "Nowy portfel" }).click();
  await expect(page.getByText(portfolioNameA)).toBeVisible();

  // F5 nie wylogowuje — silent refresh po stronie serwera odzyskuje sesję.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Twoje portfele" })).toBeVisible();

  await logoutButtons.first().click();
  await expect(page).toHaveURL(/\/login$/);

  // Regresja na wyciek izolacji danych po stronie KLIENTA: klucze w
  // `lib/queryKeys.ts` nie mają segmentu użytkownika, a `staleTime` to 60 s,
  // więc bez `queryClient.clear()` w `AuthProvider` TanStack Query pokazałby
  // użytkownikowi B listę portfeli A prosto z cache — bez odpytania backendu,
  // który sam w sobie jest poprawny (`get_owned_portfolio` → 404 na cudzy
  // zasób).
  //
  // UWAGA na kolejność: między wylogowaniem A a zalogowaniem B NIE może być
  // żadnego `page.goto()`. Wylogowanie i logowanie idą przez `router.push`
  // (nawigacja miękka), więc instancja QueryClient przeżywa zmianę sesji —
  // ale `page.goto()` to pełne przeładowanie, które kasuje cache niezależnie
  // od poprawki i test przestaje cokolwiek sprawdzać (zweryfikowane:
  // z `goto` pośrodku test przechodzi nawet z wyłączonym `clear()`).
  //
  // Scenariusz jest doklejony do testu logowania, a nie osobnym testem, z
  // tego samego powodu co scalony test w `dashboard.spec.ts`: `POST
  // /auth/login` ma limit 5/min per IP (`docs/api-kontrakt.md`), a osobny
  // test wymagałby dwóch dodatkowych logowań i przekroczyłby limit.
  await page.getByLabel("E-mail").fill(emailB);
  await page.getByLabel("Hasło").fill(password);
  await page.getByRole("button", { name: "Zaloguj się" }).click();

  await expect(page).toHaveURL(/\/portfolios$/);
  await expect(page.getByRole("heading", { name: "Twoje portfele" })).toBeVisible();
  await expect(page.getByText(portfolioNameA)).toHaveCount(0);

  // Po wylogowaniu /portfolios znów przekierowuje na /login (tu `goto` jest
  // już bezpieczne — sprawdzenie izolacji cache jest za nami).
  await logoutButtons.first().click();
  await expect(page).toHaveURL(/\/login$/);
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
