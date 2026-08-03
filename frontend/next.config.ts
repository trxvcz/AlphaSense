import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Build produkcyjny pakuje serwer i realnie używane zależności do
   * `.next/standalone` (uruchamiane przez `node server.js`, patrz
   * `frontend/Dockerfile`, stopień `prod`). Bez tego obraz produkcyjny
   * musiałby nieść całe `node_modules` i źródła.
   *
   * Nie wpływa na `npm run dev` ani na `make check` — `next build` po prostu
   * dokłada katalog `.next/standalone`.
   */
  output: "standalone",
};

/**
 * Sentry (krok 37) — opakowanie dokłada do buildu obsługę `instrumentation*.ts`
 * i identyfikator wydania. Samo w sobie nie włącza wysyłki: bez
 * `NEXT_PUBLIC_SENTRY_DSN` SDK startuje z `enabled: false`
 * (`instrumentation-client.ts`).
 *
 * **Source mapy nie lecą do Sentry, dopóki nie ma `SENTRY_AUTH_TOKEN`.**
 * Wysyłka wymaga tokenu z prawem zapisu, czyli kolejnego sekretu na maszynie
 * budującej obraz (dziś: VPS, `make prod-build`). Bez tokenu ślady stosu są
 * zminifikowane, ale nadal niosą nazwę trasy i zdarzenie; po uzupełnieniu
 * `SENTRY_AUTH_TOKEN`/`SENTRY_ORG`/`SENTRY_PROJECT` w `.env.prod` wysyłka
 * włącza się sama, bez zmiany w kodzie.
 */
export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  sourcemaps: { disable: !process.env.SENTRY_AUTH_TOKEN },
  // Bez tego każdy `next build` — także w `make check`, bez żadnego DSN —
  // dopisuje kilkanaście linii logu wtyczki.
  silent: true,
});
