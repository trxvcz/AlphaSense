/**
 * Sentry w procesie Node.js serwującym Next.js (plan krok 37).
 *
 * Ładowane przez `instrumentation.ts` tylko dla runtime'u `nodejs`. Łapie to,
 * czego konfiguracja przeglądarkowa nie widzi: błędy renderowania Server
 * Components i błędy w `server.js` obrazu standalone.
 *
 * Czyta ten sam `NEXT_PUBLIC_SENTRY_DSN`, co przeglądarka — świadomie.
 * Kontener frontendu nie dostaje `.env.prod` (nie ma po co nosić sekretów
 * backendu), a `NEXT_PUBLIC_*` jest wypieczone w buildzie, więc wartość jest
 * dostępna także tutaj bez żadnej zmiennej w compose.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

Sentry.init({
  dsn,
  enabled: Boolean(dsn),
  environment: process.env.NODE_ENV,
  sendDefaultPii: false,
  tracesSampleRate: 0,
});
