"use client";

/**
 * Heatmapa zwrotów miesięcznych (plan krok 41b).
 *
 * **Pytanie analityczne:** „czy słabe wyniki są rozłożone równomiernie, czy
 * skupione w kilku miesiącach?" Odpowiedź czyta się z układu, nie z liczby —
 * stąd siatka, a nie tabela zwrotów posortowana malejąco.
 *
 * Zbudowana z HTML-owej tabeli, nie z ECharts. Dwanaście komórek na wiersz
 * nie wymaga silnika wykresów, a tabela jest z definicji dostępna dla
 * czytnika ekranu (nagłówki wierszy i kolumn, wartość jako tekst) — kanwas
 * ECharts wymagałby osobnej alternatywy tekstowej i tak.
 *
 * Dostępność (CLAUDE.md §21): **kolor nie jest jedynym kanałem**. Liczba
 * stoi w komórce, znak jest jawny (`+`/`−`), a kierunek dodatkowo niesie
 * odcień (niebieski wzrost / pomarańczowy spadek — nie zielony/czerwony,
 * nierozróżnialne przy deuteranopii). Miesiąc bez danych jest pusty
 * i opisany, a nie pokazany jako zero.
 */
import { pct } from "@/lib/money";
import { MONTH_LABELS, heatIntensity, maxAbsReturn, monthlyGrid } from "@/lib/risk";
import type { MonthlyReturn } from "@/lib/risk";

type MonthlyReturnsHeatmapProps = {
  returns: MonthlyReturn[];
  /** Miesiąc złożony z mniej niż tylu ogniw dostaje ostrzeżenie o niepełnych danych. */
  sparseThreshold?: number;
};

const DEFAULT_SPARSE_THRESHOLD = 5;

function cellStyle(entry: MonthlyReturn, maxAbs: number): { backgroundColor: string } {
  const intensity = heatIntensity(entry.ret, maxAbs);
  // `rgba` zamiast klas Tailwinda: nasycenie jest ciągłe i zależy od danych,
  // więc nie da się go wyrazić skończonym zbiorem klas.
  const alpha = (0.12 + intensity * 0.55).toFixed(3);
  return Number(entry.ret) < 0
    ? { backgroundColor: `rgba(234, 88, 12, ${alpha})` }
    : { backgroundColor: `rgba(37, 99, 235, ${alpha})` };
}

export function MonthlyReturnsHeatmap({
  returns,
  sparseThreshold = DEFAULT_SPARSE_THRESHOLD,
}: MonthlyReturnsHeatmapProps) {
  const grid = monthlyGrid(returns);
  const maxAbs = maxAbsReturn(returns);

  if (grid.length === 0) {
    return (
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Brak zwrotów miesięcznych — portfel nie ma jeszcze pełnego miesiąca historii wyceny.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] border-separate border-spacing-1 text-sm">
        <caption className="sr-only">
          Zwroty miesięczne portfela, wiersz na rok, kolumna na miesiąc. Puste komórki oznaczają
          miesiące bez danych.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="text-left font-medium text-zinc-600 dark:text-zinc-400">
              Rok
            </th>
            {MONTH_LABELS.map((label) => (
              <th
                key={label}
                scope="col"
                className="font-medium text-zinc-600 dark:text-zinc-400"
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.map((row) => (
            <tr key={row.year}>
              <th
                scope="row"
                className="text-left font-medium text-zinc-700 dark:text-zinc-300"
              >
                {row.year}
              </th>
              {row.months.map((entry, monthIndex) => {
                const monthLabel = `${MONTH_LABELS[monthIndex]} ${row.year}`;
                if (entry === null) {
                  return (
                    <td
                      key={monthIndex}
                      className="rounded px-1 py-1 text-center text-zinc-400 dark:text-zinc-600"
                    >
                      <span className="sr-only">{monthLabel}: brak danych</span>
                      <span aria-hidden="true">—</span>
                    </td>
                  );
                }
                const sparse = entry.links < sparseThreshold;
                return (
                  <td
                    key={monthIndex}
                    style={cellStyle(entry, maxAbs)}
                    className="rounded px-1 py-1 text-center tabular-nums text-zinc-900 dark:text-zinc-100"
                  >
                    <span className="sr-only">
                      {monthLabel}: {pct(entry.ret)}
                      {sparse ? `, dane niepełne — ${entry.links} dni z wyceną` : ""}
                    </span>
                    <span aria-hidden="true">
                      {pct(entry.ret)}
                      {sparse && <span title="Dane niepełne — mało dni z wyceną">*</span>}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
        Gwiazdka oznacza miesiąc policzony z mniej niż {sparseThreshold} dni z wyceną — zwrot jest
        wtedy niepełny. Puste komórki to miesiące bez danych, a nie zwrot zerowy.
      </p>
    </div>
  );
}
