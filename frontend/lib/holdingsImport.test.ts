import { describe, expect, it } from "vitest";
import { summarizeReport, type ImportReport } from "@/lib/holdingsImport";

function report(partial: Partial<ImportReport>): ImportReport {
  return { dry_run: false, created: 0, merged: 0, skipped: 0, rows: [], ...partial };
}

describe("summarizeReport", () => {
  it("mówi wprost o dodaniu ilości, nie o aktualizacji", () => {
    expect(summarizeReport(report({ merged: 1 }))).toBe(
      "Zaimportowano: 1 pozycja z dodaną ilością.",
    );
  });

  it("odmienia liczebniki dla 2-4 i 5+", () => {
    expect(summarizeReport(report({ created: 3 }))).toBe("Zaimportowano: 3 nowe pozycje.");
    expect(summarizeReport(report({ created: 7 }))).toBe("Zaimportowano: 7 nowych pozycji.");
  });

  it("traktuje nastki jako formę mnogą dopełniaczową", () => {
    expect(summarizeReport(report({ skipped: 13 }))).toBe(
      "Zaimportowano: 13 pominiętych wierszy.",
    );
  });

  it("łączy wszystkie trzy kategorie w kolejności zdarzeń", () => {
    expect(summarizeReport(report({ created: 2, merged: 1, skipped: 4 }))).toBe(
      "Zaimportowano: 2 nowe pozycje, 1 pozycja z dodaną ilością, 4 pominięte wiersze.",
    );
  });

  it("odróżnia podgląd od zapisu", () => {
    expect(summarizeReport(report({ dry_run: true, created: 1 }))).toBe(
      "Podgląd: 1 nowa pozycja.",
    );
  });

  it("nie udaje sukcesu przy pustym pliku", () => {
    expect(summarizeReport(report({}))).toBe("Plik nie zawierał żadnych pozycji.");
  });
});
