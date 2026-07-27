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
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "mobile-375",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } },
    },
  ],
});
