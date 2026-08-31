import { withSentryConfig } from "@sentry/nextjs";
import withSerwistInit from "@serwist/next";
import createNextIntlPlugin from "next-intl/plugin";
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
 * PWA (krok 49) — Serwist kompiluje `app/sw.ts` do `public/sw.js` i wstrzykuje
 * manifest precache'u bieżącego buildu.
 *
 * **Wyłączony w devie świadomie.** Service worker w `next dev` serwuje
 * zbuforowane moduły obok Fast Refresh i daje „zmiana nie działa, aż zrobisz
 * hard reload" — objaw, który kosztuje więcej czasu niż jest wart. PWA
 * testujemy na buildzie produkcyjnym (`npm run build && npm run start`).
 *
 * **Ścieżka wyjścia z zepsutego SW:** ustawienie `disable: true` i wydanie
 * buildu sprawia, że Serwist generuje worker, który sam się wyrejestrowuje —
 * to jest ta „ścieżka wyjścia", której wymaga ryzyko zapisane w planie etapu 9.
 */
const withSerwist = withSerwistInit({
  swSrc: "app/sw.ts",
  swDest: "public/sw.js",
  disable: process.env.NODE_ENV === "development",
  // Karta, która wróciła do sieci, przeładowuje się sama — inaczej po
  // odzyskaniu zasięgu użytkownik zostaje na ekranie zbudowanym z cache'u.
  reloadOnOnline: true,
});

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
/**
 * i18n (krok 50) — wtyczka podpina `i18n/request.ts`, dzięki czemu
 * `getTranslations`/`useTranslations` mają skąd wziąć katalog. Bez routingu
 * po języku: jeden język, żadnego prefiksu w URL (patrz `lib/i18n.ts`).
 */
const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

export default withSentryConfig(withNextIntl(withSerwist(nextConfig)), {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  sourcemaps: { disable: !process.env.SENTRY_AUTH_TOKEN },
  // Bez tego każdy `next build` — także w `make check`, bez żadnego DSN —
  // dopisuje kilkanaście linii logu wtyczki.
  silent: true,
});
