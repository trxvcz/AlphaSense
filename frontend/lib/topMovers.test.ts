/**
 * Wybór „top ruchów dnia" (`lib/topMovers.ts`, krok 32).
 *
 * Najciekawszy przypadek to `slice(-topN).reverse()` dla spadków — łatwo
 * napisać go tak, że pokazuje TRZY NAJSŁABSZE spadki zamiast trzech
 * największych, a przy portfelu z dokładnie trzema spadkami obie wersje dają
 * ten sam wynik i błąd nie wychodzi w ręcznym klikaniu.
 */
import { describe, expect, it } from "vitest";

import type { Holding } from "@/lib/dashboard";
import { splitTopMovers } from "@/lib/topMovers";

function holding(symbol: string, pct: string | null): Holding {
  return {
    id: `id-${symbol}`,
    asset_id: `asset-${symbol}`,
    symbol,
    quantity: "1",
    avg_cost: null,
    cost_currency: null,
    note: null,
    value_pln: "100",
    stale: false,
    as_of: "2026-07-29",
    unrealized_pl: null,
    split_suspected: false,
    price_change_1d: pct === null ? null : { abs: "1", pct },
  };
}

describe("splitTopMovers", () => {
  it("pomija pozycje bez price_change_1d zamiast pokazywać je jako 0%", () => {
    const { gainers, losers } = splitTopMovers([
      holding("BEZDANYCH", null),
      holding("WZROST", "0.05"),
    ]);

    expect(gainers.map((h) => h.symbol)).toEqual(["WZROST"]);
    expect(losers).toEqual([]);
  });

  it("zero nie trafia ani do wzrostów, ani do spadków", () => {
    const { gainers, losers } = splitTopMovers([holding("PLASKO", "0")]);

    expect(gainers).toEqual([]);
    expect(losers).toEqual([]);
  });

  it("wzrosty są malejąco i przycięte do topN", () => {
    const { gainers } = splitTopMovers(
      [
        holding("A", "0.01"),
        holding("B", "0.09"),
        holding("C", "0.05"),
        holding("D", "0.03"),
      ],
      3,
    );

    expect(gainers.map((h) => h.symbol)).toEqual(["B", "C", "D"]);
  });

  it("spadki zaczynają się od NAJWIĘKSZEGO spadku, nie od najmniejszego", () => {
    const { losers } = splitTopMovers(
      [
        holding("A", "-0.01"),
        holding("B", "-0.09"),
        holding("C", "-0.05"),
        holding("D", "-0.03"),
      ],
      3,
    );

    // -0,09 jest największym spadkiem i musi być pierwszy; -0,01 wypada poza topN.
    expect(losers.map((h) => h.symbol)).toEqual(["B", "C", "D"]);
  });

  it("rozdziela mieszany portfel na dwie listy", () => {
    const { gainers, losers } = splitTopMovers([
      holding("W1", "0.04"),
      holding("S1", "-0.02"),
      holding("W2", "0.08"),
      holding("S2", "-0.06"),
    ]);

    expect(gainers.map((h) => h.symbol)).toEqual(["W2", "W1"]);
    expect(losers.map((h) => h.symbol)).toEqual(["S2", "S1"]);
  });

  it("nie mutuje wejściowej tablicy", () => {
    const holdings = [holding("A", "0.01"), holding("B", "0.09")];
    const before = holdings.map((h) => h.symbol);

    splitTopMovers(holdings);

    expect(holdings.map((h) => h.symbol)).toEqual(before);
  });

  it("pusty portfel daje dwie puste listy, nie wyjątek", () => {
    expect(splitTopMovers([])).toEqual({ gainers: [], losers: [] });
  });
});
