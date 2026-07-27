import type { PortfolioSummary } from "@/lib/dashboard";
import { pln, pct } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { changeColorClass } from "@/lib/changeColor";

type SummaryCardProps = {
  summary: PortfolioSummary;
};

function ChangeRow({
  label,
  change,
}: {
  label: string;
  change: PortfolioSummary["change_1d"];
}) {
  if (!change) {
    return (
      <div className="flex flex-col gap-0.5">
        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
          {label}
        </span>
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          Brak danych — worker jeszcze nie zapisał wyceny
        </span>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
        {label}
      </span>
      <span className={`text-sm font-semibold ${changeColorClass(change.pct)}`}>
        {pln(change.abs)} ({pct(change.pct)})
      </span>
    </div>
  );
}

/**
 * Karta podsumowania dashboardu (plan krok 32): łączna wartość portfela,
 * zmiana 1D/YTD, znacznik daty EOD (CLAUDE.md #7 — „dane są z EOD, nie
 * udawaj realtime") i ostrzeżenie o pozycjach z nieaktualną wyceną.
 * Czysto prezentacyjny — bez `useState`/hooków, nie potrzebuje `"use client"`.
 */
export function SummaryCard({ summary }: SummaryCardProps) {
  return (
    <div className="flex flex-col gap-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
          Wartość portfela
        </span>
        <span className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          {pln(summary.value_pln)}
        </span>
        <span className="text-xs text-zinc-500 dark:text-zinc-400">
          Dane na dzień {formatDate(summary.as_of)} (EOD)
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-2">
        <ChangeRow label="Zmiana dzienna" change={summary.change_1d} />
        <ChangeRow label="Zmiana YTD" change={summary.change_ytd} />
      </div>

      {summary.stale_assets > 0 && (
        <p
          role="status"
          className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
        >
          {summary.stale_assets}{" "}
          {summary.stale_assets === 1 ? "pozycja ma" : "pozycji ma"} nieaktualną
          wycenę (brak dzisiejszej ceny lub kursu).
        </p>
      )}
    </div>
  );
}
