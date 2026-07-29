/**
 * Formatowanie kwot i procentów (`lib/money.ts`).
 *
 * Testy asertują na SEMANTYCE wyniku (separator dziesiętny przecinkiem, znak
 * procentu, liczba miejsc po przecinku), a nie na dokładnym stringu z
 * `Intl.NumberFormat` — dokładny kształt zawiera spację niełamliwą i zależy
 * od wersji ICU w Node, więc twarde porównanie do `"128 450,32 zł"` psułoby
 * się przy aktualizacji obrazu, mimo poprawnego kodu.
 */
import { describe, expect, it } from "vitest";

import { decimal, pct, pctAxis, pln } from "@/lib/money";

/** `Intl` używa spacji niełamliwej (U+00A0) i wąskiej (U+202F) jako separatora tysięcy. */
function normalize(value: string): string {
  return value.replace(/[  ]/g, " ");
}

describe("pln", () => {
  it("formatuje string dziesiętny z API jako kwotę w złotych", () => {
    const result = normalize(pln("128450.32"));
    expect(result).toContain("zł");
    expect(result).toContain("128 450,32");
  });

  it("zachowuje znak dla kwoty ujemnej (nierozliczona strata)", () => {
    expect(normalize(pln("-1234.5"))).toContain("-");
  });

  it("dokłada brakujące miejsca po przecinku", () => {
    expect(normalize(pln("7"))).toContain("7,00");
  });
});

describe("pct", () => {
  it("traktuje wartość z API jako UŁAMEK, nie liczbę procentów", () => {
    // 0.0765 to 7,65% → 7,7% po zaokrągleniu, a nie „0,1%".
    expect(normalize(pct("0.0765"))).toBe("7,7%");
  });

  it("zawsze pokazuje jedno miejsce po przecinku", () => {
    expect(normalize(pct("0.2"))).toBe("20,0%");
  });

  it("zachowuje znak dla spadku", () => {
    expect(normalize(pct("-0.031"))).toBe("-3,1%");
  });
});

describe("pctAxis", () => {
  it("obcina miejsca po przecinku — na 375 px podziałki osi muszą być krótkie", () => {
    expect(normalize(pctAxis("0.2"))).toBe("20%");
    expect(normalize(pctAxis("0.0765"))).toBe("8%");
  });
});

describe("decimal", () => {
  it("formatuje liczbę bez symbolu waluty (waluty instrumentu API nie zwraca)", () => {
    const result = normalize(decimal("10"));
    expect(result).toBe("10,00");
    expect(result).not.toContain("zł");
  });
});
