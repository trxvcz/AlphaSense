"use client";

/**
 * Wykres wartości portfela (plan krok 32) — ECharts, importowany
 * dynamicznie (`import("echarts")` w `useEffect`, CLAUDE.md #6: „ECharts
 * przez dynamiczny import (ssr: false)", Next.js/ECharts nie renderują się
 * na serwerze). Cienki komponent: inicjalizuje instancję na `ref`
 * kontenera, `setOption` przy każdej zmianie danych/zakresu/motywu.
 *
 * Dni ze `composition_change: true` (dokupienie/sprzedaż, nie zysk/strata —
 * ADR-101) są oznaczone `markPoint` w innym kolorze, żeby użytkownik nie
 * mylił skoku wartości ze zwrotem. Pod wykresem jest tabelaryczna
 * alternatywa (`<details>`) — CLAUDE.md #8, dostępność.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type {
  DefaultLabelFormatterCallbackParams,
  TooltipComponentFormatterCallbackParams,
} from "echarts";
import { ApiError } from "@/lib/api";
import { listValuations, type ValuationPoint, type ValuationRange } from "@/lib/dashboard";
import { qk } from "@/lib/queryKeys";
import { pln } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

type ValueChartProps = {
  portfolioId: string;
};

const RANGE_OPTIONS: { value: ValuationRange; label: string }[] = [
  { value: "1M", label: "1M" },
  { value: "3M", label: "3M" },
  { value: "1Y", label: "1R" },
  { value: "YTD", label: "YTD" },
  { value: "max", label: "Max" },
];

function buildChartOption(points: ValuationPoint[], isDark: boolean) {
  const axisColor = isDark ? "#a1a1aa" : "#52525b";
  const splitLineColor = isDark ? "#3f3f46" : "#e4e4e7";
  const lineColor = isDark ? "#60a5fa" : "#2563eb";
  const markerColor = isDark ? "#fbbf24" : "#f59e0b";

  const markPointData = points
    .map((point, index) => ({ point, index }))
    .filter(({ point }) => point.composition_change)
    .map(({ point }) => ({
      name: "zmiana składu",
      coord: [point.date, Number(point.value_pln)],
    }));

  return {
    backgroundColor: "transparent",
    grid: { left: 8, right: 16, top: 24, bottom: 40, containLabel: true },
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: TooltipComponentFormatterCallbackParams) => {
        const list = Array.isArray(params) ? params : [params];
        const first = list[0] as DefaultLabelFormatterCallbackParams | undefined;
        if (!first || typeof first.dataIndex !== "number") return "";
        const point = points[first.dataIndex];
        if (!point) return "";
        const note = point.composition_change
          ? "<br/><strong>zmiana składu portfela</strong>"
          : "";
        return `${formatDate(point.date)}<br/>${pln(point.value_pln)}${note}`;
      },
    },
    xAxis: {
      type: "category" as const,
      data: points.map((p) => p.date),
      boundaryGap: false,
      axisLabel: {
        color: axisColor,
        formatter: (value: string) => formatDate(value),
      },
      axisLine: { lineStyle: { color: splitLineColor } },
    },
    yAxis: {
      type: "value" as const,
      axisLabel: {
        color: axisColor,
        formatter: (value: number) => pln(String(value)),
      },
      splitLine: { lineStyle: { color: splitLineColor } },
    },
    series: [
      {
        type: "line" as const,
        data: points.map((p) => Number(p.value_pln)),
        smooth: false,
        symbol: "none" as const,
        lineStyle: { color: lineColor, width: 2 },
        areaStyle: {
          color: {
            type: "linear" as const,
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: isDark ? "rgba(96,165,250,0.25)" : "rgba(37,99,235,0.15)" },
              { offset: 1, color: "rgba(0,0,0,0)" },
            ],
          },
        },
        markPoint: {
          symbol: "diamond",
          symbolSize: 10,
          itemStyle: { color: markerColor },
          data: markPointData,
        },
      },
    ],
  };
}

export function ValueChart({ portfolioId }: ValueChartProps) {
  const [range, setRange] = useState<ValuationRange>("1M");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<import("echarts").ECharts | null>(null);
  const isDark = useIsDarkTheme();

  const valuationsQuery = useQuery({
    queryKey: qk.valuations(portfolioId, range),
    queryFn: () => listValuations(portfolioId, range),
  });

  const points = useMemo(() => valuationsQuery.data ?? [], [valuationsQuery.data]);

  // Inicjalizacja/aktualizacja wykresu — tylko gdy są dane do narysowania.
  useEffect(() => {
    if (!containerRef.current || points.length === 0) return;
    let cancelled = false;

    void import("echarts").then((echarts) => {
      if (cancelled || !containerRef.current) return;
      const chart = chartInstanceRef.current ?? echarts.init(containerRef.current);
      chartInstanceRef.current = chart;
      chart.setOption(buildChartOption(points, isDark), { notMerge: true });
    });

    return () => {
      cancelled = true;
    };
  }, [points, isDark]);

  // Resize wykresu przy zmianie rozmiaru okna (mobile-first: layout się
  // przełamuje między 375px a desktopem).
  useEffect(() => {
    function handleResize() {
      chartInstanceRef.current?.resize();
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Dispose instancji tylko przy odmontowaniu komponentu.
  useEffect(() => {
    return () => {
      chartInstanceRef.current?.dispose();
      chartInstanceRef.current = null;
    };
  }, []);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          Wartość portfela w czasie
        </h2>
        <div role="group" aria-label="Zakres wykresu" className="flex gap-1">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={range === option.value}
              onClick={() => setRange(option.value)}
              className={`rounded-md px-2 py-1 text-xs font-medium outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 ${
                range === option.value
                  ? "bg-blue-600 text-white"
                  : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {valuationsQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie wykresu"
          className="h-64 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      )}

      {valuationsQuery.isError && (
        <ErrorState
          message={
            valuationsQuery.error instanceof ApiError
              ? valuationsQuery.error.message
              : "Nie udało się wczytać historii wyceny."
          }
          onRetry={() => void valuationsQuery.refetch()}
        />
      )}

      {valuationsQuery.isSuccess && points.length === 0 && (
        <EmptyState
          title="Brak historii wyceny dla tego zakresu"
          description="Wykres pojawi się, gdy worker EOD zapisze przynajmniej dwa snapshoty wyceny portfela. Spróbuj zakresu „Max”."
        />
      )}

      {valuationsQuery.isSuccess && points.length > 0 && (
        <>
          <div ref={containerRef} className="h-64 w-full sm:h-80" />
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Dane z {formatDate(points[points.length - 1]!.date)} (EOD). Znacznik{" "}
            <span aria-hidden className="inline-block h-2 w-2 rotate-45 bg-amber-500" /> oznacza
            dzień zmiany składu portfela (dokupienie/sprzedaż), nie zwrot z inwestycji.
          </p>

          <details className="text-sm">
            <summary className="cursor-pointer text-zinc-600 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-400">
              Pokaż dane wykresu w formie tabeli
            </summary>
            <div className="mt-2 max-h-64 overflow-y-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th scope="col" className="py-1 pr-2">
                      Data
                    </th>
                    <th scope="col" className="py-1 pr-2">
                      Wartość
                    </th>
                    <th scope="col" className="py-1">
                      Zmiana składu
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((point) => (
                    <tr key={point.date}>
                      <td className="py-1 pr-2">{formatDate(point.date)}</td>
                      <td className="py-1 pr-2">{pln(point.value_pln)}</td>
                      <td className="py-1">{point.composition_change ? "tak" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
