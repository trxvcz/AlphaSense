/**
 * Import listy pozycji z CSV (`POST /portfolios/{id}/holdings/import`,
 * krok 48, etap 9).
 *
 * Plik jest czytany w przeglądarce i wysyłany jako pole JSON, nie
 * `multipart/form-data` — backend nie ma `python-multipart`, a dołożenie
 * zależności wymagałoby osobnej decyzji (CLAUDE.md §10).
 *
 * Zawartość pliku NIE jest tu parsowana ani „poprawiana": jedynym parserem
 * jest `backend/app/modules/portfolio/csv_import.py`. Druga implementacja we
 * frontendzie oznaczałaby dwie definicje formatu, które rozjadą się przy
 * pierwszej poprawce — podgląd bierzemy z `dry_run`, nie z własnej analizy.
 */
import { apiFetch } from "@/lib/api";

/** Limit rozmiaru pliku — lustro `csv_import.MAX_CHARS` po stronie backendu. */
export const MAX_CSV_CHARS = 100_000;

export type ImportRowStatus = "created" | "merged" | "skipped";

export type ImportRow = {
  /** Numer linii w PLIKU (od 1), nie pozycja na liście wyników. */
  line: number;
  symbol: string;
  status: ImportRowStatus;
  message: string | null;
};

export type ImportReport = {
  dry_run: boolean;
  created: number;
  merged: number;
  skipped: number;
  rows: ImportRow[];
};

export function importHoldings(
  portfolioId: string,
  content: string,
  dryRun: boolean,
): Promise<ImportReport> {
  return apiFetch<ImportReport>(`/portfolios/${portfolioId}/holdings/import`, {
    method: "POST",
    body: { content, dry_run: dryRun },
  });
}

/**
 * Podsumowanie raportu jednym zdaniem, po polsku, z odmianą liczebnika.
 *
 * Mówi wprost o **dodaniu ilości**, a nie o „zaktualizowaniu": import scala
 * się z tym, co już jest w portfelu, i to jest ta część, której użytkownik
 * może się nie spodziewać.
 */
export function summarizeReport(report: ImportReport): string {
  const parts: string[] = [];
  if (report.created > 0) {
    parts.push(`${report.created} ${plural(report.created, "nowa pozycja", "nowe pozycje", "nowych pozycji")}`);
  }
  if (report.merged > 0) {
    parts.push(
      `${report.merged} ${plural(report.merged, "pozycja z dodaną ilością", "pozycje z dodaną ilością", "pozycji z dodaną ilością")}`,
    );
  }
  if (report.skipped > 0) {
    parts.push(`${report.skipped} ${plural(report.skipped, "pominięty wiersz", "pominięte wiersze", "pominiętych wierszy")}`);
  }
  if (parts.length === 0) {
    return "Plik nie zawierał żadnych pozycji.";
  }
  const prefix = report.dry_run ? "Podgląd: " : "Zaimportowano: ";
  return `${prefix}${parts.join(", ")}.`;
}

/**
 * Polska odmiana liczebnika (1 / 2-4 / 5+), z wyjątkiem nastek (12-14 idą
 * do formy mnogiej dopełniaczowej) — ta sama zasada co `pluralSessions`
 * w `lib/candles.ts`.
 */
function plural(count: number, one: string, few: string, many: string): string {
  const abs = Math.abs(count);
  if (abs === 1) return one;
  const lastTwo = abs % 100;
  if (lastTwo >= 12 && lastTwo <= 14) return many;
  const last = abs % 10;
  return last >= 2 && last <= 4 ? few : many;
}
