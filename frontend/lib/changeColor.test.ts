/**
 * Kolor zmiany wg znaku (`lib/changeColor.ts`).
 *
 * Testowane są trzy GAŁĘZIE (wzrost / spadek / zero), nie konkretne nazwy
 * klas Tailwinda — zmiana odcienia zieleni jest decyzją wizualną i nie
 * powinna psuć testu. Wyjątkiem jest para jasny/ciemny: brak wariantu
 * `dark:` oznacza tekst nieczytelny w trybie ciemnym, więc to sprawdzamy
 * wprost.
 */
import { describe, expect, it } from "vitest";

import { changeColorClass } from "@/lib/changeColor";

describe("changeColorClass", () => {
  it("dodatnia zmiana dostaje inny kolor niż ujemna", () => {
    expect(changeColorClass("0.05")).not.toBe(changeColorClass("-0.05"));
  });

  it("zero jest neutralne — nie zielone i nie czerwone", () => {
    const neutral = changeColorClass("0");
    expect(neutral).not.toBe(changeColorClass("0.05"));
    expect(neutral).not.toBe(changeColorClass("-0.05"));
  });

  it("każdy wariant ma odpowiednik dla trybu ciemnego", () => {
    for (const value of ["0.05", "-0.05", "0"]) {
      expect(changeColorClass(value)).toContain("dark:");
    }
  });

  it("bardzo mała dodatnia zmiana nadal liczy się jako wzrost", () => {
    // Regresja na wypadek zaokrąglania progu do zera przy formatowaniu:
    // 0,0001 wyświetli się jako „0,0%", ale znakiem jest wzrost.
    expect(changeColorClass("0.0001")).toBe(changeColorClass("0.05"));
  });
});
