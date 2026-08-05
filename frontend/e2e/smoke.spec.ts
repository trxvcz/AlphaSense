import { test, expect, type Page } from "@playwright/test";

/**
 * Smoke test Fazy 1 (plan krok 39) — jedno przejście dokładnie tą ścieżką,
 * którą plan uznaje za kryterium ukończenia: *„wpisujesz pozycje, widzisz
 * wartość, skład % i ranking rynków"*.
 *
 * Dwie rzeczy odróżniają go od `dashboard.spec.ts`, który pokrywa te same
 * ekrany znacznie dokładniej:
 *
 * 1. **Wszystko idzie przez UI.** Ani jedno żądanie do API nie jest tu
 *    składane ręcznie — konto, portfel i pozycja powstają przez formularze,
 *    a przejścia między widokami przez nawigację. Dzięki temu ten sam plik
 *    da się puścić na produkcję (`E2E_BASE_URL=https://…`), gdzie nie mamy
 *    ani tokenu, ani prawa dopisywania czegokolwiek do bazy z boku.
 * 2. **Biegnie w DWÓCH projektach** (`mobile-375` i `desktop`), więc
 *    rozmiaru okna NIE ustawia sam — bierze go z projektu. Nawigacja jest
 *    klikana przez „ten link, który akurat widać", czyli na telefonie
 *    sprawdza `BottomNav`, a na desktopie `SideNav`.
 *
 * Ten test jest CELOWO płytki w asercjach i szeroki w zasięgu. Regresje
 * pojedynczych komponentów łapią `dashboard.spec.ts` i Vitest; tutaj
 * chodzi o jedno pytanie — czy świeżo wdrożony stack (Caddy → frontend →
 * API → Postgres → Redis → dane z workera) przeprowadza nowego użytkownika
 * od rejestracji do trzech liczb, dla których powstał produkt.
 *
 * **Czerwona wartość portfela zaraz po wdrożeniu zwykle nie jest błędem
 * kodu, tylko brakiem danych EOD**: worker rejestruje joby przy starcie
 * (ADR-102) i czeka na swoją godzinę. Wymuszenie:
 * `docker compose … exec worker python -m app.cli ingest --market CRYPTO`.
 *
 * Aktywo jest parametrem, bo baza produkcyjna dostaje wyłącznie
 * `seed_reference` — są w niej indeksy rynków, nie ma demo CDR/PKN/AAPL.
 * `bitcoin` jest jedynym aktywem obecnym w OBU środowiskach (indeks rynku
 * CRYPTO, `app/db/seed.py`), stąd taki domyślny wybór.
 */
const ASSET_QUERY = process.env.E2E_SMOKE_ASSET ?? "bitcoin";
const QUANTITY = process.env.E2E_SMOKE_QUANTITY ?? "0.05";

function uniqueEmail(): string {
  return `smoke-${Date.now()}-${Math.floor(Math.random() * 1e6)}@alphasense.example`;
}

/**
 * Link nawigacji widoczny przy TYM rozmiarze okna. `BottomNav` i `SideNav`
 * renderują te same pozycje (`lib/navItems.ts`) i oba siedzą w DOM-ie —
 * ukrywa je CSS. Bez filtra `visible` selektor jest niejednoznaczny, a
 * `.first()`/`.last()` wskazywałoby raz na dobry, raz na ukryty element,
 * zależnie od projektu.
 */
function visibleLink(page: Page, name: string) {
  return page.getByRole("link", { name, exact: true }).filter({ visible: true });
}

async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

test("smoke Fazy 1: rejestracja → portfel → pozycja → wartość → struktura % → rynki", async ({
  page,
}, testInfo) => {
  const shot = (name: string) =>
    page.screenshot({
      path: `test-results/smoke-${testInfo.project.name}-${name}.png`,
      fullPage: true,
    });

  const email = uniqueEmail();
  const password = "SmokeTest123";
  const portfolioName = `Portfel smoke ${Date.now()}`;

  // --- 1. Rejestracja (od razu loguje) ---
  await page.goto("/register");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Hasło").fill(password);
  await page.getByRole("button", { name: "Załóż konto" }).click();
  await expect(page).toHaveURL(/\/portfolios$/);

  // --- 2. Pierwszy portfel ---
  await expect(page.getByText("Nie masz jeszcze żadnego portfela")).toBeVisible();
  await page.getByLabel("Nazwa portfela").fill(portfolioName);
  await page.getByRole("button", { name: "Nowy portfel" }).click();
  await page.getByRole("link", { name: new RegExp(portfolioName) }).click();
  await expect(page).toHaveURL(/\/portfolios\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: portfolioName })).toBeVisible();

  // --- 3. Pierwsza pozycja przez formularz ---
  await page.getByRole("button", { name: "Dodaj pierwszą pozycję" }).click();
  await page.getByLabel("Aktywo").fill(ASSET_QUERY);
  // Autouzupełnianie ma 300 ms debouncu, a `/assets/search` potrafi dobierać
  // metadane w tle — `click()` sam czeka na pojawienie się opcji.
  await page.getByRole("option", { name: new RegExp(ASSET_QUERY, "i") }).first().click();
  await page.getByLabel("Ilość").fill(QUANTITY);
  await page.getByRole("button", { name: "Dodaj pozycję", exact: true }).click();
  await expect(page.getByText("Ten portfel nie ma jeszcze żadnej pozycji")).toHaveCount(0);

  // --- 4. Wartość w PLN ---
  await expect(page.getByText("Wartość portfela", { exact: true })).toBeVisible();
  const value = page.getByText(/zł/).first();
  await expect(value).toBeVisible();
  // Wartość musi być NIEZEROWA. „0,00 zł" to dokładnie ten stan, w którym
  // aplikacja wygląda na działającą, a produkt nie działa: pozycja jest
  // w bazie, ale wycena nie ma z czego powstać (brak `prices`, brak kursu
  // NBP, albo worker nigdy nie odpalił). Sam napis „zł" tego nie wyłapie.
  await expect(value).toHaveText(/[1-9]/);
  await expect(page.getByText(/Dane na dzień/)).toBeVisible();
  await shot("wartosc");

  // --- 5. Skład procentowy ---
  // Przez nawigację globalną, nie po URL-u: użytkownik ma dokładnie jeden
  // portfel, więc `PortfolioPicker` musi go wybrać sam i przekierować
  // (`router.replace`), zamiast pokazywać ekran pośredni.
  await visibleLink(page, "Struktura").click();
  await expect(page).toHaveURL(/\/portfolios\/[0-9a-f-]+\/struktura$/);
  await expect(page.getByRole("heading", { name: new RegExp(portfolioName) })).toBeVisible();
  await expect(page.getByRole("img", { name: "Wykres kołowy alokacji" })).toBeVisible();

  // Tabela pod wykresem jest jedynym miejscem, gdzie skład da się przeczytać
  // bez oglądania kanwy — i jednocześnie tym, co czyta czytnik ekranu.
  await page.getByText("Pokaż dane wykresu w formie tabeli").click();
  await expect(page.getByRole("columnheader", { name: "Udział" })).toBeVisible();
  await expect(page.getByRole("cell", { name: /%/ }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Koncentracja portfela" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await shot("struktura");

  // --- 6. Ranking rynków ---
  await visibleLink(page, "Rynki").click();
  await expect(page).toHaveURL(/\/portfolios\/[0-9a-f-]+\/rynki$/);
  const marketRows = page
    .getByRole("list", { name: "Rynki wg udziału w portfelu" })
    .getByRole("listitem");
  await expect(marketRows.first()).toBeVisible();
  await expect(marketRows.first().getByText(/%/).first()).toBeVisible();
  await expectNoHorizontalScroll(page);
  await shot("rynki");
});
