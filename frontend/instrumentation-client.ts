/**
 * Sentry po stronie przeglądarki (plan krok 37).
 *
 * Next.js sam ładuje ten plik z korzenia projektu przed hydratacją — stąd
 * nazwa, nie jest importowany nigdzie ręcznie.
 *
 * DSN jest `NEXT_PUBLIC_*`, więc **wypieka się w bundle na etapie
 * `next build`** (`frontend/Dockerfile`, `args:` w `docker-compose.prod.yml`)
 * — zmiana DSN wymaga przebudowy obrazu, nie restartu kontenera. To nie
 * przeoczenie: klucz publiczny Sentry z definicji jedzie do przeglądarki
 * każdego użytkownika, nie jest sekretem.
 *
 * Bez DSN (dev, `make check`, Playwright) `enabled: false` wyłącza SDK
 * całkowicie — żadnych żądań sieciowych z testów.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

Sentry.init({
  dsn,
  enabled: Boolean(dsn),
  environment: process.env.NODE_ENV,
  // Bez PII: żadnych adresów IP ani nagłówków `Authorization` w zdarzeniu.
  // Access token żyje w tej aplikacji wyłącznie w pamięci (`lib/tokenStore`),
  // ale wysyłany jest w nagłówku każdego żądania — a te trafiają do Sentry
  // jako „breadcrumbs" po żądaniach `fetch`.
  sendDefaultPii: false,
  // Tracing wyłączony — krok 37 to alerty o błędach, nie profilowanie
  // (ta sama decyzja co po stronie backendu, `app/core/observability.py`).
  tracesSampleRate: 0,
});

/**
 * Wymagane przez App Router, żeby błąd rzucony w trakcie nawigacji klienckiej
 * miał w Sentry poprawną trasę źródłową, a nie tę, z której użytkownik wyszedł.
 */
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
