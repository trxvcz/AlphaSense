import { describe, expect, it } from "vitest";

import { heatIntensity, maxAbsReturn, monthlyGrid, type MonthlyReturn } from "@/lib/risk";

function month(year: number, m: number, ret: string, links = 20): MonthlyReturn {
  return { year, month: m, ret, links };
}

describe("monthlyGrid", () => {
  it("rozkłada zwroty na siatkę rok × 12 miesięcy", () => {
    const grid = monthlyGrid([month(2026, 1, "0.05"), month(2026, 3, "-0.02")]);

    expect(grid).toHaveLength(1);
    expect(grid[0].year).toBe(2026);
    expect(grid[0].months).toHaveLength(12);
    expect(grid[0].months[0]?.ret).toBe("0.05");
    expect(grid[0].months[2]?.ret).toBe("-0.02");
  });

  it("zostawia `null` w miesiącach bez danych, a nie zero", () => {
    // Sedno tej funkcji: zero znaczy „nic nie zarobił", brak znaczy „nie
    // wiemy", a na heatmapie wyglądałyby identycznie.
    const grid = monthlyGrid([month(2026, 1, "0.05")]);

    expect(grid[0].months[1]).toBeNull();
    expect(grid[0].months.filter((m) => m !== null)).toHaveLength(1);
  });

  it("sortuje lata malejąco — najnowszy u góry", () => {
    const grid = monthlyGrid([month(2024, 1, "0.01"), month(2026, 1, "0.02"), month(2025, 1, "0.03")]);

    expect(grid.map((row) => row.year)).toEqual([2026, 2025, 2024]);
  });

  it("dla pustego wejścia daje pustą siatkę, nie rok bez danych", () => {
    expect(monthlyGrid([])).toEqual([]);
  });
});

describe("maxAbsReturn", () => {
  it("bierze największy moduł, niezależnie od znaku", () => {
    expect(maxAbsReturn([month(2026, 1, "0.05"), month(2026, 2, "-0.12")])).toBeCloseTo(0.12);
  });

  it("dla pustej listy daje zero", () => {
    expect(maxAbsReturn([])).toBe(0);
  });
});

describe("heatIntensity", () => {
  it("skaluje liniowo względem maksimum", () => {
    expect(heatIntensity("0.06", 0.12)).toBeCloseTo(0.5);
    expect(heatIntensity("-0.12", 0.12)).toBeCloseTo(1);
  });

  it("nie przekracza 1", () => {
    expect(heatIntensity("0.5", 0.12)).toBe(1);
  });

  it("daje 0 zamiast NaN, gdy wszystkie zwroty są zerowe", () => {
    // `NaN` w `rgba()` znaczy „komórka bez tła", czyli wygląda dokładnie
    // jak brak danych — a to co innego niż zwrot zerowy.
    expect(heatIntensity("0", 0)).toBe(0);
  });
});
