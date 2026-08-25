/**
 * Dostęp do kalendarza dywidend (`GET /portfolios/{id}/dividends`, krok 47,
 * etap 9) — jedyne miejsce, które woła `apiFetch` dla tego zasobu
 * (docs/konwencje.md: „Bez fetch rozsianego po komponentach").
 *
 * Kształt odpowiedzi 1:1 z `docs/api-kontrakt.md` i `dividends/schemas.py`.
 * Kwoty to STRINGI dziesiętne (CLAUDE.md #3.1).
 *
 * Poza typami i wywołaniem siedzą tu **czyste funkcje opisujące dane**
 * (`daysUntil`, `coverageNote`), testowane bez DOM-u w `lib/dividends.test.ts`
 * — wzorzec `lib/news.ts` + `lib/news.test.ts`.
 */
import { apiFetch } from "@/lib/api";

export type DividendEvent = {
  symbol: string;
  market_code: string;
  /** `YYYY-MM-DD`. Jedyna data zawsze obecna — od niej zależy prawo do wypłaty. */
  ex_date: string;
  record_date: string | null;
  pay_date: string | null;
  declaration_date: string | null;
  /** Brutto, na jedną akcję, w walucie notowania. Nie w PLN i nie po podatku. */
  amount_per_share: string;
  currency: string;
  quantity: string;
  /** `amount_per_share × quantity` — szacunek dla DZISIEJSZEJ wielkości pozycji. */
  estimated_gross: string;
  source: string;
  fetched_at: string;
};

export type DividendCalendar = {
  items: DividendEvent[];
  horizon_days: number;
  assets_covered: number;
  /** Symbole pozycji, o które nie mamy kogo zapytać (dziś: cała GPW). */
  assets_without_coverage: string[];
  /** Rynki, z których ŻADNA pozycja portfela nie ma pokrycia danymi. */
  uncovered_markets: string[];
};

export function getPortfolioDividends(
  portfolioId: string,
  options: { horizonDays?: number } = {},
): Promise<DividendCalendar> {
  const params = new URLSearchParams();
  if (options.horizonDays !== undefined) params.set("horizon_days", String(options.horizonDays));
  const query = params.toString();
  return apiFetch<DividendCalendar>(
    `/portfolios/${portfolioId}/dividends${query ? `?${query}` : ""}`,
  );
}

/**
 * Ile dni do ex-daty, licząc od `today` (obie daty jako `YYYY-MM-DD`).
 *
 * Liczone na **datach kalendarzowych w UTC**, nie na `Date.now()`: ex-data
 * jest datą giełdową bez godziny, więc mieszanie jej z lokalnym czasem
 * użytkownika dawałoby „za 2 dni" i „za 1 dzień" dla tego samego zdarzenia
 * w zależności od strefy i pory dnia.
 */
export function daysUntil(exDate: string, today: string): number {
  const ms = Date.parse(`${exDate}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`);
  return Math.round(ms / 86_400_000);
}

/** Dzisiejsza data w formacie `YYYY-MM-DD` (UTC — patrz `daysUntil`). */
export function todayIso(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/**
 * Zdanie o zasięgu danych albo `null`, gdy kalendarz pokrywa cały portfel.
 *
 * **To nie jest ozdobnik.** Portfel złożony z polskich spółek dostaje dziś
 * pusty kalendarz, bo darmowy dostawca nie pokrywa GPW — i bez tego zdania
 * pustka znaczyłaby „nic Cię nie czeka" zamiast „nie mamy danych"
 * (CLAUDE.md #3.15). Zwracany `null` (a nie pusty string) po to, żeby
 * komponent nie renderował pustego akapitu dla portfela w pełni pokrytego.
 */
export function coverageNote(calendar: DividendCalendar): string | null {
  if (calendar.assets_without_coverage.length === 0) return null;
  const markets =
    calendar.uncovered_markets.length > 0
      ? ` Nie obejmujemy dziś rynków: ${calendar.uncovered_markets.join(", ")}.`
      : "";
  return (
    `Kalendarz nie obejmuje pozycji: ${calendar.assets_without_coverage.join(", ")} — ` +
    `nie mamy dla nich źródła danych o dywidendach, więc brak wpisu NIE znaczy, ` +
    `że dywidendy nie będzie.${markets}`
  );
}
