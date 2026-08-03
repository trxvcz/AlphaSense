/**
 * Punkt wejścia instrumentacji serwera Next.js (plan krok 37).
 *
 * Next woła `register()` raz, przy starcie procesu serwera. Konfiguracja
 * Sentry jest w osobnym pliku i ładowana dynamicznie, bo `register()` biega
 * także w runtime `edge`, gdzie import SDK dla Node'a by się wywalił — ta
 * aplikacja nie ma dziś tras edge, więc tamtej gałęzi po prostu nie ma.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
}

/**
 * Błędy rzucone w Server Components / route handlerach App Routera nie
 * przechodzą przez żaden `try` w naszym kodzie — Next raportuje je tym
 * hookiem, a bez niego widać by je było wyłącznie w logach kontenera.
 */
export { captureRequestError as onRequestError } from "@sentry/nextjs";
