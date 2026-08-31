/**
 * Wejście next-intl po stronie serwera (plan krok 50, etap 9).
 *
 * Wołane raz na żądanie; zwraca język i katalog komunikatów. Przy jednym
 * języku jest to stała — patrz `lib/i18n.ts`, gdzie opisany jest powód
 * rezygnacji z segmentu `[locale]` w URL.
 */
import { getRequestConfig } from "next-intl/server";
import { LOCALE, TIME_ZONE } from "@/lib/i18n";

export default getRequestConfig(async () => ({
  locale: LOCALE,
  timeZone: TIME_ZONE,
  messages: (await import(`../messages/${LOCALE}.json`)).default,
}));
