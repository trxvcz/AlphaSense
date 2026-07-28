/**
 * Karta koncentracji portfela (plan krok 33) — udział pięciu największych
 * pozycji, liczba wycenionych pozycji i HHI z interpretacją.
 *
 * Interpretację („niska"/„średnia"/„wysoka") liczy backend
 * (`analytics/service.py::_interpretation`) — UI jej NIE wylicza ponownie z
 * `hhi`, żeby progi żyły w jednym miejscu (skill `analityka-struktury`:
 * „nie rozsiane po UI"). Tutaj mapujemy tylko gotowy wynik na kolor, i to
 * zawsze razem z etykietą tekstową — sam kolor nigdy nie niesie znaczenia.
 */
import type { Concentration } from "@/lib/analytics";
import { pct } from "@/lib/money";

type ConcentrationCardProps = {
  concentration: Concentration;
};

const INTERPRETATION_CLASS: Record<string, string> = {
  niska: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  średnia: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  wysoka: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
};

export function ConcentrationCard({ concentration }: ConcentrationCardProps) {
  const badgeClass =
    INTERPRETATION_CLASS[concentration.interpretation] ??
    "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-200";

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          Koncentracja portfela
        </h2>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
          {concentration.interpretation}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div>
          <dt className="text-xs text-zinc-600 dark:text-zinc-400">Udział top 5</dt>
          <dd className="text-xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
            {pct(concentration.top5_share)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-600 dark:text-zinc-400">Pozycji wycenionych</dt>
          <dd className="text-xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
            {concentration.count}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-600 dark:text-zinc-400">HHI</dt>
          <dd className="text-xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
            {concentration.hhi}
          </dd>
        </div>
      </dl>

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        HHI to suma kwadratów udziałów pozycji: im bliżej 1, tym bardziej portfel stoi na
        pojedynczych aktywach. Liczone po pozycjach, nie po koszykach — i tylko po pozycjach,
        które udało się wycenić.
      </p>
    </div>
  );
}
