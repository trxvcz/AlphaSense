/**
 * Testy czystych funkcji z `lib/performance.ts` (plan krok 42).
 *
 * Wyrównanie serii po osi X to jedyne miejsce we frontendzie, gdzie da się
 * po cichu pokazać zwroty benchmarku przypisane do niewłaściwych dat —
 * ECharts rysuje serię jako tablicę równoległą do osi kategorii, więc każdy
 * brakujący dzień przesuwałby całą linię w lewo.
 */
import { describe, expect, it } from "vitest";
import {
  alignBenchmark,
  benchmarkNotice,
  type Benchmark,
  type BenchmarkPoint,
  type PerformancePoint,
} from "@/lib/performance";

function point(date: string, index: string): PerformancePoint {
  return { date, value_pln: "1000", ret: null, index };
}

function benchmarkPoint(date: string, index: string): BenchmarkPoint {
  return { date, as_of: date, index };
}

function benchmark(overrides: Partial<Benchmark> = {}): Benchmark {
  return {
    key: "WIG20",
    symbol: "ETFBW20TR",
    label: "WIG20 (przez Beta ETF WIG20TR)",
    currency: "PLN",
    approximate: false,
    note: null,
    unavailable_reason: null,
    outperformance: "6.0000",
    points: [benchmarkPoint("2026-01-05", "104")],
    ...overrides,
  };
}

describe("alignBenchmark", () => {
  it("ustawia benchmark na tych samych datach co portfel", () => {
    const points = [point("2026-01-02", "100"), point("2026-01-05", "110")];
    const benchmark = [benchmarkPoint("2026-01-02", "100"), benchmarkPoint("2026-01-05", "120")];

    expect(alignBenchmark(points, benchmark)).toEqual([100, 120]);
  });

  it("zostawia lukę zamiast przesuwać serię, gdy brakuje dnia", () => {
    const points = [
      point("2026-01-02", "100"),
      point("2026-01-05", "110"),
      point("2026-01-06", "115"),
    ];
    const benchmark = [benchmarkPoint("2026-01-02", "100"), benchmarkPoint("2026-01-06", "120")];

    expect(alignBenchmark(points, benchmark)).toEqual([100, null, 120]);
  });

  it("ignoruje dni benchmarku spoza okna portfela", () => {
    const points = [point("2026-01-05", "100")];
    const benchmark = [benchmarkPoint("2026-01-02", "90"), benchmarkPoint("2026-01-05", "100")];

    expect(alignBenchmark(points, benchmark)).toEqual([100]);
  });

  it("pusty benchmark daje same luki, nie zera", () => {
    expect(alignBenchmark([point("2026-01-02", "100")], [])).toEqual([null]);
  });
});

describe("benchmarkNotice", () => {
  /**
   * To jest jedyna rzecz, której ten ekran naprawdę musi dopilnować:
   * przybliżenie ma być oznaczone jako przybliżenie (CLAUDE.md #3.15).
   * WIG20 liczony z ETF-a `ETFBW20TR` NIE JEST indeksem WIG20 i widok nie
   * może udawać, że jest.
   */
  it("oznacza serię przybliżoną razem z uzasadnieniem", () => {
    const notice = benchmarkNotice(
      benchmark({ approximate: true, note: "Liczone z ETF-a Beta WIG20TR." }),
    );

    expect(notice).toEqual({ kind: "approximate", note: "Liczone z ETF-a Beta WIG20TR." });
  });

  it("brak serii ma pierwszeństwo przed przybliżeniem", () => {
    // Oba komunikaty naraz sugerowałyby, że jakaś linia jednak jest.
    const notice = benchmarkNotice(
      benchmark({
        approximate: true,
        note: "Liczone z ETF-a Beta WIG20TR.",
        unavailable_reason: "Brak notowań na dzień startu lub wcześniej.",
        points: [],
      }),
    );

    expect(notice).toEqual({
      kind: "unavailable",
      reason: "Brak notowań na dzień startu lub wcześniej.",
    });
  });

  it("seria dokładna nie ma czego komunikować", () => {
    expect(benchmarkNotice(benchmark())).toBeNull();
  });

  it("brak benchmarku to nie to samo co benchmark bez danych", () => {
    // `null` = użytkownik nie wybrał porównania. Żadnego ostrzeżenia.
    expect(benchmarkNotice(null)).toBeNull();
  });

  it("przybliżenie bez noty nadal jest oznaczone", () => {
    // `note` jest opisem, nie warunkiem — brak opisu nie może uciszyć flagi.
    expect(benchmarkNotice(benchmark({ approximate: true, note: null }))).toEqual({
      kind: "approximate",
      note: null,
    });
  });
});
