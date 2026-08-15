/**
 * Dostęp do `GET /portfolios/{id}/performance` (plan kroki 40 i 42) — zwrot
 * za okres, seria indeksu łańcuchowego i opcjonalna seria porównawcza.
 * Jedyne miejsce wołające `apiFetch` dla tego zasobu (docs/konwencje.md).
 *
 * Kształty 1:1 z `docs/api-kontrakt.md`. Kwoty i ułamki są `string`ami —
 * konwersja na `number` wyłącznie na potrzeby wykresu, nigdy do liczenia
 * czegokolwiek, co trafia z powrotem do użytkownika (CLAUDE.md §8).
 */
import { apiFetch } from "@/lib/api";
import type { ValuationRange } from "@/lib/dashboard";

/**
 * `WIG20` jest liczone z ETF-a `ETFBW20TR` — sam indeks nie ma dostępnego
 * źródła historii (decyzja 8 planu etapu 8). Odpowiedź niesie `symbol`,
 * `approximate` i `note`, więc widok pokazuje to wprost.
 */
export type BenchmarkKey = "WIG20" | "^GSPC";

export type PerformancePoint = {
  date: string;
  value_pln: string;
  /** `null` = zwrotu za ten dzień NIE ZNAMY (pierwszy punkt albo zerwane ogniwo). */
  ret: string | null;
  index: string;
};

export type BenchmarkPoint = {
  date: string;
  /** Data notowania, z którego pochodzi wartość — bywa wcześniejsza niż `date`. */
  as_of: string;
  index: string;
};

export type Benchmark = {
  key: string;
  symbol: string;
  label: string;
  /** `null`, gdy serii nie da się policzyć — nie ma wtedy waluty do podania. */
  currency: string | null;
  approximate: boolean;
  note: string | null;
  /** Niepuste ⇒ `points` puste. Tekst jest gotowy do wyświetlenia. */
  unavailable_reason: string | null;
  /**
   * Różnica portfel − benchmark na koniec okna, w punktach procentowych.
   * Liczona przez backend na `Decimal` i podana jako string — wynik trafia
   * do użytkownika, więc front go nie przelicza (CLAUDE.md §8).
   */
  outperformance: string | null;
  points: BenchmarkPoint[];
};

export type Performance = {
  range: string;
  /** `null` = brak zwrotu (portfel bez historii), co jest czym innym niż `"0"`. */
  period_return: string | null;
  first_date: string | null;
  last_date: string | null;
  links: number;
  skipped_composition_change: number;
  skipped_zero_base: number;
  points: PerformancePoint[];
  benchmark: Benchmark | null;
};

export function getPerformance(
  portfolioId: string,
  range: ValuationRange,
  benchmark: BenchmarkKey | null,
): Promise<Performance> {
  const params = new URLSearchParams({ range });
  if (benchmark !== null) params.set("benchmark", benchmark);
  return apiFetch<Performance>(`/portfolios/${portfolioId}/performance?${params.toString()}`);
}

export type BenchmarkOption = {
  value: BenchmarkKey | "none";
  label: string;
};

export const BENCHMARK_OPTIONS: readonly BenchmarkOption[] = [
  { value: "none", label: "Bez porównania" },
  { value: "WIG20", label: "WIG20" },
  { value: "^GSPC", label: "S&P 500" },
];

/**
 * Serie do wykresu wyrównane po osi X.
 *
 * Benchmark nie musi mieć punktu na każdej dacie portfela (notowanie sprzed
 * pierwszej sesji w oknie po prostu nie istnieje), a ECharts rysuje serię
 * jako tablicę równoległą do osi kategorii. Bez tego wyrównania druga linia
 * przesunęłaby się w lewo o brakujące dni — czyli pokazałaby zwroty
 * benchmarku przypisane do niewłaściwych dat.
 *
 * `null` w tablicy zostawia lukę w linii zamiast łączyć przez nieznane dni.
 */
export function alignBenchmark(
  points: PerformancePoint[],
  benchmarkPoints: BenchmarkPoint[],
): (number | null)[] {
  const byDate = new Map(benchmarkPoints.map((p) => [p.date, p.index]));
  return points.map((p) => {
    const value = byDate.get(p.date);
    return value === undefined ? null : Number(value);
  });
}

/**
 * Co widok ma powiedzieć o jakości serii benchmarku, zanim pokaże liczby.
 *
 * Wyciągnięte z komponentu do `lib/` **celowo**: `vitest.config.ts` trzyma
 * testy na czystych funkcjach (render pokrywa Playwright), a to jest
 * dokładnie ten przypadek, który tamten komentarz przewiduje — decyzja
 * „czy oznaczyć dane jako przybliżone" jest logiką, nie układem pikseli,
 * i realizuje CLAUDE.md #3.15. Bez tego jedyna rzecz, której ten ekran
 * naprawdę musi dopilnować, nie miała testu.
 *
 * `null` znaczy „nic do zakomunikowania": seria jest pełna i dokładna.
 */
export type BenchmarkNotice =
  | { kind: "unavailable"; reason: string }
  | { kind: "approximate"; note: string | null };

export function benchmarkNotice(benchmark: Benchmark | null): BenchmarkNotice | null {
  if (benchmark === null) return null;
  // Brak serii ma pierwszeństwo przed przybliżeniem: „nie ma danych" i „dane
  // są przybliżone" to dwa różne komunikaty, a pokazanie obu naraz sugeruje,
  // że jakaś linia jednak jest.
  if (benchmark.unavailable_reason !== null) {
    return { kind: "unavailable", reason: benchmark.unavailable_reason };
  }
  if (benchmark.approximate) return { kind: "approximate", note: benchmark.note };
  return null;
}
