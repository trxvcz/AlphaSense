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
  outperformance,
  type BenchmarkPoint,
  type PerformancePoint,
} from "@/lib/performance";

function point(date: string, index: string): PerformancePoint {
  return { date, value_pln: "1000", ret: null, index };
}

function benchmarkPoint(date: string, index: string): BenchmarkPoint {
  return { date, as_of: date, index };
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

describe("outperformance", () => {
  it("liczy różnicę w punktach na koniec okresu", () => {
    const points = [point("2026-01-02", "100"), point("2026-01-05", "110")];
    const benchmark = [benchmarkPoint("2026-01-02", "100"), benchmarkPoint("2026-01-05", "104")];

    expect(outperformance(points, benchmark)).toBe(6);
  });

  it("ujemna różnica, gdy portfel przegrał z rynkiem", () => {
    const points = [point("2026-01-05", "95")];
    const benchmark = [benchmarkPoint("2026-01-05", "110")];

    expect(outperformance(points, benchmark)).toBe(-15);
  });

  it("brak którejkolwiek serii daje null, nie zero", () => {
    expect(outperformance([], [benchmarkPoint("2026-01-05", "110")])).toBeNull();
    expect(outperformance([point("2026-01-05", "100")], [])).toBeNull();
  });
});
