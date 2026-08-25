import { describe, expect, it } from "vitest";

import { coverageNote, daysUntil, todayIso, type DividendCalendar } from "@/lib/dividends";

function calendar(overrides: Partial<DividendCalendar> = {}): DividendCalendar {
  return {
    items: [],
    horizon_days: 90,
    assets_covered: 1,
    assets_without_coverage: [],
    uncovered_markets: [],
    ...overrides,
  };
}

describe("daysUntil", () => {
  it("liczy różnicę dni kalendarzowych", () => {
    expect(daysUntil("2026-08-30", "2026-08-23")).toBe(7);
    expect(daysUntil("2026-08-23", "2026-08-23")).toBe(0);
  });

  it("nie gubi się na zmianie czasu (30.10 → 2.11 to 3 dni, mimo 25 godzin doby)", () => {
    // Liczenie na lokalnym czasie dałoby tu 2,96 dnia i po zaokrągleniu
    // w dół — 2. Ex-data jest datą giełdową, nie momentem.
    expect(daysUntil("2026-11-02", "2026-10-30")).toBe(3);
  });
});

describe("todayIso", () => {
  it("zwraca datę UTC w formacie YYYY-MM-DD", () => {
    expect(todayIso(new Date("2026-08-23T23:30:00Z"))).toBe("2026-08-23");
  });
});

describe("coverageNote", () => {
  it("milczy, gdy kalendarz pokrywa cały portfel", () => {
    expect(coverageNote(calendar())).toBeNull();
  });

  it("nazywa pozycje bez pokrycia i nieobjęte rynki", () => {
    const note = coverageNote(
      calendar({ assets_without_coverage: ["PKN", "CDR"], uncovered_markets: ["GPW"] }),
    );
    expect(note).toContain("PKN");
    expect(note).toContain("CDR");
    expect(note).toContain("GPW");
    // Najważniejsze zdanie tego ekranu: brak wpisu ≠ brak dywidendy.
    expect(note).toContain("NIE znaczy");
  });
});
