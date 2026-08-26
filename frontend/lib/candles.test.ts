/**
 * Testy czystych funkcji świec (`lib/candles.ts`, krok 45) — bez DOM-u
 * i bez sieci.
 */
import { describe, expect, it } from "vitest";

import {
  completenessNote,
  pluralSessions,
  toChartCandles,
  type Candle,
  type CandleSeries,
} from "@/lib/candles";

function candle(overrides: Partial<Candle> = {}): Candle {
  return {
    date: "2026-01-02",
    open: "50.00000000",
    high: "55.00000000",
    low: "45.00000000",
    close: "50.00000000",
    volume: 1000,
    ...overrides,
  };
}

function series(overrides: Partial<CandleSeries> = {}): CandleSeries {
  return {
    symbol: "CDR",
    name: "CD Projekt",
    currency: "PLN",
    range: "1Y",
    skipped: 0,
    candles: [candle()],
    ...overrides,
  };
}

describe("toChartCandles", () => {
  it("zamienia stringi na liczby TYLKO na potrzeby rysowania", () => {
    const [point] = toChartCandles([candle()]);

    expect(point).toEqual({ time: "2026-01-02", open: 50, high: 55, low: 45, close: 50 });
  });

  it("zachowuje kolejność i nie gubi punktów", () => {
    const points = toChartCandles([
      candle({ date: "2026-01-02" }),
      candle({ date: "2026-01-03" }),
    ]);

    expect(points.map((p) => p.time)).toEqual(["2026-01-02", "2026-01-03"]);
  });
});

describe("completenessNote", () => {
  it("milczy, gdy seria jest kompletna", () => {
    expect(completenessNote(series())).toBeNull();
  });

  it("mówi wprost, ile sesji wypadło — dziura w wykresie jest niewidoczna", () => {
    expect(completenessNote(series({ skipped: 3 }))).toContain("3 sesje");
  });
});

describe("pluralSessions", () => {
  it("odmienia po polsku", () => {
    expect(pluralSessions(1)).toBe("sesję");
    expect(pluralSessions(2)).toBe("sesje");
    expect(pluralSessions(4)).toBe("sesje");
    expect(pluralSessions(5)).toBe("sesji");
    // 12-14 to wyjątek od reguły końcówki: „12 sesji", nie „12 sesje".
    expect(pluralSessions(12)).toBe("sesji");
    expect(pluralSessions(22)).toBe("sesje");
    expect(pluralSessions(25)).toBe("sesji");
  });
});
