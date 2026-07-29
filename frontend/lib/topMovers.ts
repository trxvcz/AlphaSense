/**
 * Wybór „top ruchów dnia" (plan krok 32) — czysta logika wyciągnięta z
 * `components/dashboard/TopMovers.tsx`, żeby dała się przetestować bez DOM-u
 * i bez API (pierwsza fala testów Vitest, backlog etapu 6).
 *
 * Pozycje bez `price_change_1d` (mniej niż dwa notowania w historii) są
 * POMIJANE, nie pokazywane jako 0% — brak danych i brak zmiany to dwie różne
 * rzeczy (ta sama zasada co „nie licz jako zero" po stronie backendu).
 */
import type { Holding } from "@/lib/dashboard";

export type MovingHolding = Holding & {
  price_change_1d: NonNullable<Holding["price_change_1d"]>;
};

export function hasPriceChange(holding: Holding): holding is MovingHolding {
  return holding.price_change_1d !== null;
}

export const TOP_N = 3;

export type TopMoversSplit = {
  /** Wzrosty, malejąco (największy wzrost pierwszy). */
  gainers: MovingHolding[];
  /** Spadki, rosnąco co do wartości zmiany (największy spadek pierwszy). */
  losers: MovingHolding[];
};

/**
 * Dzieli pozycje na największe wzrosty i największe spadki.
 *
 * Zero (`pct === "0"`) nie trafia do żadnej z list — to nie jest ani wzrost,
 * ani spadek, a wypełnianie nim listy „największych spadków" przy spokojnej
 * sesji byłoby mylące.
 *
 * Lista spadków jest odwracana po przycięciu (`slice(-topN).reverse()`), więc
 * pierwszy element to NAJWIĘKSZY spadek — obie kolumny czyta się wtedy tak
 * samo: od góry, od najmocniejszego ruchu.
 */
export function splitTopMovers(holdings: Holding[], topN: number = TOP_N): TopMoversSplit {
  const withChange = holdings.filter(hasPriceChange);
  const sorted = [...withChange].sort(
    (a, b) => Number(b.price_change_1d.pct) - Number(a.price_change_1d.pct),
  );

  return {
    gainers: sorted.filter((h) => Number(h.price_change_1d.pct) > 0).slice(0, topN),
    losers: sorted
      .filter((h) => Number(h.price_change_1d.pct) < 0)
      .slice(-topN)
      .reverse(),
  };
}
