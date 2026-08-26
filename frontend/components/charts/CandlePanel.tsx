"use client";

/**
 * Panel świecowy: przełącznik zakresu + wykres + opis (plan krok 45).
 *
 * Jeden komponent na dwa zastosowania — aktywo i indeks rynku — bo pytanie
 * jest identyczne („jak zachowywał się kurs"), a różni się tylko źródło
 * danych. Stąd `fetcher` w propsach zamiast dwóch bliźniaczych komponentów.
 *
 * Opis pod wykresem nie jest ozdobą: kanwas jest dla czytnika ekranu pusty,
 * a seria niepełna wygląda dokładnie jak kompletna (CLAUDE.md #3.15, §21).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import {
  CANDLE_RANGES,
  completenessNote,
  toChartCandles,
  type CandleRange,
  type CandleSeries,
} from "@/lib/candles";
import { formatDate } from "@/lib/dates";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { CandleChart } from "@/components/charts/CandleChart";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

type CandlePanelProps = {
  queryKey: (range: CandleRange) => readonly unknown[];
  fetcher: (range: CandleRange) => Promise<CandleSeries>;
  /** Zakres startowy — świece czyta się w kontekście trendu, stąd 1Y. */
  defaultRange?: CandleRange;
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function CandlePanel({ queryKey, fetcher, defaultRange = "1Y" }: CandlePanelProps) {
  const [range, setRange] = useState<CandleRange>(defaultRange);
  const isDark = useIsDarkTheme();

  const seriesQuery = useQuery({
    queryKey: queryKey(range),
    queryFn: () => fetcher(range),
  });

  const series = seriesQuery.data;
  const chartCandles = useMemo(
    () => (series ? toChartCandles(series.candles) : []),
    [series],
  );

  const note = series ? completenessNote(series) : null;
  const first = series?.candles[0];
  const last = series?.candles[series.candles.length - 1];

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          Notowania {series ? `— ${series.symbol}` : ""}
        </h2>
        <div role="group" aria-label="Zakres wykresu" className="flex flex-wrap gap-1">
          {CANDLE_RANGES.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={range === value}
              onClick={() => setRange(value)}
              className={`rounded-md px-2 py-1 text-xs font-medium outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 ${
                range === value
                  ? "bg-blue-600 text-white"
                  : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              }`}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      {seriesQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie notowań"
          className="h-72 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      )}

      {seriesQuery.isError && (
        <ErrorState
          message={apiErrorMessage(seriesQuery.error, "Nie udało się wczytać notowań.")}
          onRetry={() => void seriesQuery.refetch()}
        />
      )}

      {series && series.candles.length === 0 && (
        <EmptyState
          title="Brak notowań w tym zakresie"
          description="Dla tego instrumentu nie mamy jeszcze świec w wybranym okresie. Spróbuj szerszego zakresu — dane EOD napływają raz dziennie."
        />
      )}

      {series && series.candles.length > 0 && (
        <>
          <CandleChart
            candles={chartCandles}
            isDark={isDark}
            ariaLabel={`Wykres świecowy ${series.symbol}, ${series.candles.length} sesji`}
          />
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {series.name} ({series.symbol}) · {series.candles.length} sesji od{" "}
            {first ? formatDate(first.date) : "—"} do {last ? formatDate(last.date) : "—"} ·
            ostatnie zamknięcie {last?.close} {series.currency}.
          </p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Ceny <strong>skorygowane</strong> o splity i dywidendy — ta sama podstawa co
            wycena portfela, więc świeca sprzed splitu stoi na dzisiejszej skali.
          </p>
          {note && (
            <p
              role="note"
              className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200"
            >
              {note}
            </p>
          )}
        </>
      )}
    </div>
  );
}
