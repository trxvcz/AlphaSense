/**
 * Dostęp do `GET /portfolios/{id}/risk` (plan krok 41b) — zmienność,
 * Sharpe, max drawdown z serią underwater, beta i zwroty miesięczne.
 * Jedyne miejsce wołające `apiFetch` dla tego zasobu (docs/konwencje.md).
 *
 * Kształty 1:1 z `docs/api-kontrakt.md`. Ułamki są `string`ami — konwersja
 * na `number` wyłącznie na potrzeby wykresu, nigdy do liczenia czegokolwiek,
 * co wraca do użytkownika (CLAUDE.md §8).
 *
 * **Każda metryka ma własne `*_unavailable_reason`.** To nie jest ozdoba
 * kontraktu: przy tej samej serii zmienność bywa policzalna, a Sharpe nie
 * (brak stopy referencyjnej NBP). Widok pokazuje powód, a nie pustkę.
 */
import { apiFetch } from "@/lib/api";
import type { ValuationRange } from "@/lib/dashboard";
import type { BenchmarkKey } from "@/lib/performance";

export type Drawdown = {
  /** Ujemny (`"-0.2300"` = spadek o 23%). Znak niesie kierunek. */
  value: string;
  peak_date: string;
  trough_date: string;
  /** `null` = jeszcze nieodrobione, co jest czym innym niż odrobione dawno temu. */
  recovered_at: string | null;
};

export type UnderwaterPoint = {
  date: string;
  /** `0` na szczycie, wartości ujemne poniżej. */
  value: string;
};

export type MonthlyReturn = {
  year: number;
  month: number;
  ret: string;
  /** Liczba ogniw — miesiąc z 3 dni i z 20 wygląda tak samo, a znaczy co innego. */
  links: number;
};

export type Beta = {
  key: string;
  symbol: string;
  label: string;
  approximate: boolean;
  value: string | null;
  observations: number;
  unavailable_reason: string | null;
};

export type Risk = {
  range: string;
  first_date: string | null;
  last_date: string | null;
  observations: number;
  min_observations: number;
  volatility: string | null;
  volatility_unavailable_reason: string | null;
  sharpe: string | null;
  sharpe_unavailable_reason: string | null;
  /** Czym liczono Sharpe'a — dana musi być identyfikowalna co do źródła. */
  risk_free_label: string | null;
  max_drawdown: Drawdown | null;
  underwater: UnderwaterPoint[];
  monthly_returns: MonthlyReturn[];
  beta: Beta | null;
};

export function getRisk(
  portfolioId: string,
  range: ValuationRange,
  benchmark: BenchmarkKey | null,
): Promise<Risk> {
  const params = new URLSearchParams({ range });
  if (benchmark !== null) params.set("benchmark", benchmark);
  return apiFetch<Risk>(`/portfolios/${portfolioId}/risk?${params.toString()}`);
}

export const MONTH_LABELS = [
  "sty",
  "lut",
  "mar",
  "kwi",
  "maj",
  "cze",
  "lip",
  "sie",
  "wrz",
  "paź",
  "lis",
  "gru",
] as const;

/**
 * Zwroty miesięczne rozłożone na siatkę rok × miesiąc.
 *
 * Miesiąc bez danych zostaje `null`, a NIE zerem — to jest cały powód, dla
 * którego ta funkcja istnieje zamiast `Array(12).fill(0)`. Zero znaczy
 * „portfel nic nie zarobił", brak znaczy „nie wiemy", a na heatmapie
 * wyglądałyby identycznie (CLAUDE.md #3.15).
 *
 * Lata idą malejąco (najnowszy u góry) — heatmapa czytana jest od tego, co
 * najświeższe.
 */
export function monthlyGrid(
  returns: MonthlyReturn[],
): { year: number; months: (MonthlyReturn | null)[] }[] {
  if (returns.length === 0) return [];
  const byYear = new Map<number, (MonthlyReturn | null)[]>();
  for (const entry of returns) {
    let row = byYear.get(entry.year);
    if (row === undefined) {
      row = Array<MonthlyReturn | null>(12).fill(null);
      byYear.set(entry.year, row);
    }
    row[entry.month - 1] = entry;
  }
  return [...byYear.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, months]) => ({ year, months }));
}

/**
 * Nasycenie tła komórki heatmapy: 0 dla zera, 1 dla największego co do
 * modułu zwrotu w całej siatce. Skala jest **wspólna dla wszystkich
 * komórek**, inaczej dwa miesiące o tym samym zwrocie miałyby różny kolor.
 *
 * Zwraca 0, gdy wszystkie zwroty są zerowe — dzielenie przez zero dałoby
 * `NaN`, a `NaN` w `rgba()` znaczy „komórka bez tła", czyli wygląda jak brak
 * danych.
 */
export function heatIntensity(value: string, maxAbs: number): number {
  if (maxAbs <= 0) return 0;
  const magnitude = Math.abs(Number(value));
  if (!Number.isFinite(magnitude)) return 0;
  return Math.min(magnitude / maxAbs, 1);
}

/** Największy co do modułu zwrot w siatce — wspólna skala heatmapy. */
export function maxAbsReturn(returns: MonthlyReturn[]): number {
  return returns.reduce((max, entry) => {
    const magnitude = Math.abs(Number(entry.ret));
    return Number.isFinite(magnitude) && magnitude > max ? magnitude : max;
  }, 0);
}
