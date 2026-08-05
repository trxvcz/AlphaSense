import { defineConfig, devices } from "@playwright/test";

/**
 * Konfiguracja Playwright — testy E2E przeciw już uruchomionemu stackowi
 * dev (`docker compose up`, `frontend` na :3000, `api` na :8000). Nie
 * startuje serwerów sam (`webServer` pominięte świadomie) — CI/lokalnie
 * uruchamiasz `docker compose up -d` przed `npx playwright test`.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  // Domyślne 5 s jest za mało dla smoke testu (krok 39), który z założenia
  // biegnie przeciw ZIMNEMU stackowi: świeżo wdrożona produkcja albo dopiero
  // co podniesiony kontener dev kompiluje trasę przy pierwszym wejściu, a
  // wycena idzie do bazy bez rozgrzanego cache'u Redisa. Jedno takie
  // przekroczenie zdarzyło się przy pisaniu tego testu (pierwszy przebieg po
  // recreate kontenera), a false negative w smoke teście jest kosztowniejszy
  // niż kilka sekund czekania — to on decyduje, czy wdrożenie uznajemy za
  // udane.
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    // Pełna suita jedzie na 375 px — to jest rozmiar, przy którym UI się
    // psuje pierwszy, a wszystkie widoki są projektowane mobile first
    // (CLAUDE.md sekcja 8, skill `next-widok`).
    {
      name: "mobile-375",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } },
    },
    // Desktop dostaje WYŁĄCZNIE smoke test (plan krok 39: „smoke test na
    // telefonie i desktopie"). Puszczanie na nim całej suity podwoiłoby
    // czas i liczbę logowań, nic nowego nie sprawdzając: `dashboard.spec.ts`
    // sam przełącza rozmiar okna w trakcie testu, a `auth.spec.ts` bada
    // dokładnie zachowanie mobilne. Smoke jest jedynym plikiem, który
    // rozmiaru NIE ustawia sam — bierze go z projektu.
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } },
      testMatch: /smoke\.spec\.ts/,
    },
  ],
});
