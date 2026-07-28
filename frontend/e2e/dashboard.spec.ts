import { test, expect } from "@playwright/test";

/**
 * Dashboard portfela (plan krok 32) — happy path z realnymi danymi.
 * Formularz dodawania pozycji nie istnieje jeszcze (krok 35), więc portfele
 * i pozycje są przygotowane bezpośrednio przez API (`request` fixture).
 * Logowanie idzie tylko RAZ przez UI (i raz przez API do przygotowania
 * danych) — `POST /auth/login` ma dedykowany limit 5/minutę per IP
 * (`docs/api-kontrakt.md`, „Rate limiting"), więc jeden test robi
 * wszystko (desktop + mobile + pusty portfel) zamiast logować się
 * osobno w kilku testach.
 */
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000/api";

function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@alphasense.example`;
}

test("dashboard portfela: podsumowanie, wykres, top ruchy dnia, mobile 375px, portfel pusty", async ({
  page,
  request,
}) => {
  const email = uniqueEmail("e2e-dashboard");
  const password = "TestPass123";

  const registerResponse = await request.post(`${API_URL}/auth/register`, {
    data: { email, password },
  });
  expect(registerResponse.ok()).toBeTruthy();

  const loginResponse = await request.post(`${API_URL}/auth/login`, {
    data: { email, password },
  });
  expect(loginResponse.ok()).toBeTruthy();
  const { access_token: accessToken } = (await loginResponse.json()) as {
    access_token: string;
  };
  const authHeaders = { Authorization: `Bearer ${accessToken}` };

  const portfolioResponse = await request.post(`${API_URL}/portfolios`, {
    headers: authHeaders,
    data: { name: "Portfel e2e dashboard", type: "standard" },
  });
  expect(portfolioResponse.ok()).toBeTruthy();
  const portfolio = (await portfolioResponse.json()) as { id: string };

  const emptyPortfolioResponse = await request.post(`${API_URL}/portfolios`, {
    headers: authHeaders,
    data: { name: "Portfel pusty e2e", type: "standard" },
  });
  const emptyPortfolio = (await emptyPortfolioResponse.json()) as { id: string };

  // Aktywa z historią notowań (patrz seed demo) — CDR/PKN (GPW, PLN),
  // bitcoin (CRYPTO, USD) — dają realne value_pln i price_change_1d.
  const searchCdr = await request.get(`${API_URL}/assets/search?q=CDR`);
  const [cdr] = (await searchCdr.json()) as { id: string; symbol: string }[];
  const searchPkn = await request.get(`${API_URL}/assets/search?q=PKN`);
  const [pkn] = (await searchPkn.json()) as { id: string; symbol: string }[];
  const searchBtc = await request.get(`${API_URL}/assets/search?q=bitcoin`);
  const [btc] = (await searchBtc.json()) as { id: string; symbol: string }[];

  for (const [asset, quantity] of [
    [cdr, "10"],
    [pkn, "25"],
    [btc, "0.1"],
  ] as const) {
    const holdingResponse = await request.post(
      `${API_URL}/portfolios/${portfolio.id}/holdings`,
      { headers: authHeaders, data: { asset_id: asset.id, quantity } },
    );
    expect(holdingResponse.ok()).toBeTruthy();
  }

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Hasło").fill(password);
  await page.getByRole("button", { name: "Zaloguj się" }).click();
  await expect(page).toHaveURL(/\/portfolios$/);

  // --- Desktop ---
  await page.goto(`/portfolios/${portfolio.id}`);
  await expect(page.getByRole("heading", { name: "Portfel e2e dashboard" })).toBeVisible();

  // Karta podsumowania — wartość portfela sformatowana w PLN.
  await expect(page.getByText("Wartość portfela", { exact: true })).toBeVisible();
  await expect(page.getByText(/zł/).first()).toBeVisible();
  await expect(page.getByText(/Dane na dzień/)).toBeVisible();

  // Wykres — brak historii snapshotów dla świeżo utworzonego portfela
  // (worker jeszcze nie zapisał wyceny) -> stan pusty, nie błąd.
  await expect(page.getByText("Brak historii wyceny dla tego zakresu")).toBeVisible();
  // Przełącznik zakresu jest widoczny i można kliknąć inny zakres.
  await page.getByRole("button", { name: "Max", exact: true }).click();
  await expect(page.getByRole("button", { name: "Max", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // Top ruchy dnia — przynajmniej jedna pozycja ma price_change_1d.
  await expect(page.getByRole("heading", { name: "Top ruchy dnia" })).toBeVisible();

  await page.screenshot({ path: "test-results/dashboard-desktop.png", fullPage: true });

  // --- Mobile 375px ---
  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Portfel e2e dashboard" })).toBeVisible();
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);

  // Etykiety w dolnej nawigacji nie mogą być przycięte. Brak poziomego
  // scrolla strony tego NIE wykrywa: pasek ma stałą szerokość i ściska
  // pozycje wewnętrznie, więc dołożenie kolejnego elementu urwie etykiety
  // przy nadal zielonej asercji wyżej. Dziś margines jest wąski (66 px na
  // „Dashboard", dokładnie tyle, ile zajmuje tekst), więc każdy piąty link
  // albo szósty element paska trzeba zweryfikować tym testem.
  const navOverflow = await page
    .getByRole("navigation", { name: "Nawigacja główna" })
    .last()
    .evaluate((nav) =>
      Array.from(nav.querySelectorAll("a")).filter(
        (link) => link.scrollWidth > link.clientWidth,
      ).length,
    );
  expect(navOverflow).toBe(0);
  await page.screenshot({ path: "test-results/dashboard-mobile-375.png", fullPage: true });

  // --- Portfel pusty -> EmptyState z CTA ---
  await page.goto(`/portfolios/${emptyPortfolio.id}`);
  await expect(page.getByText("Ten portfel nie ma jeszcze żadnej pozycji")).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-empty-375.png", fullPage: true });

  // --- Krok 35: formularz dodawania pozycji ---
  // Dopisane do TEGO testu, nie osobnego: `POST /auth/login` ma limit 5/min
  // per IP, a suita zużywa już wszystkie sloty (patrz `auth.spec.ts`).
  await page.getByRole("button", { name: "Dodaj pierwszą pozycję" }).click();
  await expect(page.getByRole("heading", { name: "Dodaj pozycję" })).toBeVisible();

  // Autouzupełnianie tickera — debounce 300 ms, więc czekamy na wynik.
  await page.getByLabel("Aktywo").fill("CDR");
  await page.getByRole("option", { name: new RegExp(cdr.symbol) }).click();

  await page.getByLabel("Ilość").fill("3");
  await page.getByRole("button", { name: "Dodaj pozycję", exact: true }).click();

  // Po dodaniu formularz się zamyka, a portfel przestaje być pusty —
  // unieważnienie `qk.holdings` przeładowuje widok bez F5.
  await expect(page.getByText("Ten portfel nie ma jeszcze żadnej pozycji")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Top ruchy dnia" })).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-po-dodaniu-375.png", fullPage: true });

  // --- Krok 35: tryb ciemny/jasny ---
  // Motyw steruje klasą `dark` na <html> (`lib/theme.ts` + `app/globals.css`),
  // więc sprawdzamy dokładnie to, na czym stoją wszystkie klasy `dark:`.
  const html = page.locator("html");
  const themeButton = page.getByRole("button", { name: /^Motyw:/ }).first();

  // Cykl ma TRZY stany (system → jasny → ciemny), więc jedno kliknięcie nie
  // musi zmienić wyglądu: Playwright startuje w schemacie jasnym, czyli
  // „system" i „jasny" wyglądają identycznie. Klikamy aż do konkretnego stanu.
  async function selectTheme(label: string): Promise<void> {
    for (let i = 0; i < 3; i += 1) {
      const current = await themeButton.getAttribute("aria-label");
      if (current?.startsWith(label)) return;
      await themeButton.click();
    }
    throw new Error(`Nie udało się ustawić motywu: ${label}`);
  }

  await selectTheme("Motyw: ciemny");
  await expect.poll(() => html.evaluate((el) => el.classList.contains("dark"))).toBe(true);

  await selectTheme("Motyw: jasny");
  await expect.poll(() => html.evaluate((el) => el.classList.contains("dark"))).toBe(false);

  // Wybór przeżywa pełne przeładowanie (localStorage + skrypt anty-migotanie
  // w `app/layout.tsx`) — bez tego użytkownik z motywem ciemnym dostawałby
  // błysk białego tła przy każdym wejściu.
  await selectTheme("Motyw: ciemny");
  await page.reload();
  await expect.poll(() => html.evaluate((el) => el.classList.contains("dark"))).toBe(true);
  await expect(themeButton).toHaveAttribute("aria-label", /^Motyw: ciemny/);
});
