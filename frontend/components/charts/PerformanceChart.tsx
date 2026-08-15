"use client";

/**
 * Wykres wyników portfela na tle benchmarku (plan kroki 40 i 42) — ECharts
 * przez dynamiczny import, ten sam wzorzec co `ValueChart.tsx`.
 *
 * **Rysuje indeks łańcuchowy (baza 100), nie wartość w PLN.** To jest cała
 * różnica względem `ValueChart`: wpłata podnosi wartość portfela, ale nie
 * jego wynik, a porównanie z rynkiem ma sens tylko na wielkościach
 * znormalizowanych do wspólnego startu. Obie serie zaczynają się od 100
 * w tym samym dniu.
 *
 * Dostępność (CLAUDE.md §21): serie różnią się nie tylko kolorem, ale też
 * stylem linii (benchmark przerywany) — czerwony/zielony ani sam kolor nie
 * mogą być jedynym kanałem informacji. Pod wykresem jest tabelaryczna
 * alternatywa, a przybliżenie benchmarku jest opisane słowem, nie ikoną.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type {
  DefaultLabelFormatterCallbackParams,
  TooltipComponentFormatterCallbackParams,
} from "echarts";
import { ApiError } from "@/lib/api";
import type { ValuationRange } from "@/lib/dashboard";
import {
  alignBenchmark,
  getPerformance,
  benchmarkNotice,
  BENCHMARK_OPTIONS,
  type Benchmark,
  type BenchmarkKey,
  type PerformancePoint,
} from "@/lib/performance";
import { qk } from "@/lib/queryKeys";
import { decimal, pct } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

type PerformanceChartProps = {
  portfolioId: string;
};

const RANGE_OPTIONS: { value: ValuationRange; label: string }[] = [
  { value: "1M", label: "1M" },
  { value: "3M", label: "3M" },
  { value: "1Y", label: "1R" },
  { value: "YTD", label: "YTD" },
  { value: "max", label: "Max" },
];

function buildChartOption(
  points: PerformancePoint[],
  benchmark: Benchmark | null,
  // Wyrównana seria przychodzi z zewnątrz, policzona RAZ — patrz `alignedBenchmark`
  // w komponencie. Wcześniej liczyła ją i ta funkcja, i każdy wiersz tabeli.
  benchmarkData: (number | null)[] | null,
  isDark: boolean,
) {
  const axisColor = isDark ? "#a1a1aa" : "#52525b";
  const splitLineColor = isDark ? "#3f3f46" : "#e4e4e7";
  const portfolioColor = isDark ? "#60a5fa" : "#2563eb";
  const benchmarkColor = isDark ? "#c084fc" : "#7c3aed";

  return {
    backgroundColor: "transparent",
    grid: { left: 8, right: 16, top: 24, bottom: 40, containLabel: true },
    legend: benchmarkData !== null ? { top: 0, textStyle: { color: axisColor } } : undefined,
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: TooltipComponentFormatterCallbackParams) => {
        const list = Array.isArray(params) ? params : [params];
        const first = list[0] as DefaultLabelFormatterCallbackParams | undefined;
        if (!first || typeof first.dataIndex !== "number") return "";
        const point = points[first.dataIndex];
        if (!point) return "";
        const rows = list
          .map((entry) => {
            const item = entry as DefaultLabelFormatterCallbackParams;
            const value = typeof item.value === "number" ? item.value.toFixed(2) : "brak danych";
            return `${item.marker ?? ""} ${item.seriesName}: ${value}`;
          })
          .join("<br/>");
        // Zwrot dzienny portfela: `null` znaczy „nie znamy", nie „zero" —
        // dzień zmiany składu nie ma zwrotu (ADR-101).
        const note =
          point.ret === null
            ? "<br/><strong>zmiana składu — brak zwrotu za ten dzień</strong>"
            : "";
        return `${formatDate(point.date)}<br/>${rows}${note}`;
      },
    },
    xAxis: {
      type: "category" as const,
      data: points.map((p) => p.date),
      boundaryGap: false,
      axisLabel: { color: axisColor, formatter: (value: string) => formatDate(value) },
      axisLine: { lineStyle: { color: splitLineColor } },
    },
    yAxis: {
      type: "value" as const,
      scale: true,
      axisLabel: { color: axisColor },
      splitLine: { lineStyle: { color: splitLineColor } },
    },
    series: [
      {
        name: "Portfel",
        type: "line" as const,
        data: points.map((p) => Number(p.index)),
        smooth: false,
        symbol: "none" as const,
        lineStyle: { color: portfolioColor, width: 2 },
      },
      ...(benchmarkData !== null
        ? [
            {
              name: benchmark?.label ?? "Benchmark",
              type: "line" as const,
              data: benchmarkData,
              smooth: false,
              symbol: "none" as const,
              // Przerywana linia — kształt, nie tylko kolor (CLAUDE.md §21).
              lineStyle: { color: benchmarkColor, width: 2, type: "dashed" as const },
              connectNulls: false,
            },
          ]
        : []),
    ],
  };
}

export function PerformanceChart({ portfolioId }: PerformanceChartProps) {
  const [range, setRange] = useState<ValuationRange>("1Y");
  const [benchmarkKey, setBenchmarkKey] = useState<BenchmarkKey | "none">("WIG20");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<import("echarts").ECharts | null>(null);
  const isDark = useIsDarkTheme();

  const benchmark = benchmarkKey === "none" ? null : benchmarkKey;
  const performanceQuery = useQuery({
    queryKey: qk.performance(portfolioId, range, benchmark),
    queryFn: () => getPerformance(portfolioId, range, benchmark),
  });

  const data = performanceQuery.data;
  const points = useMemo(() => data?.points ?? [], [data]);
  const benchmarkData = data?.benchmark ?? null;
  // Jedno wyrównanie na render, nie jedno na wiersz tabeli. Poprzednia wersja
  // wołała `alignBenchmark` wewnątrz `points.map`, czyli budowała `Map` z całej
  // serii benchmarku raz na wiersz — przy `range=max` (ok. 1300 snapshotów)
  // dawało to ~1,7 mln operacji przy każdym otwarciu tabeli.
  const alignedBenchmark = useMemo(
    () =>
      benchmarkData !== null && benchmarkData.points.length > 0
        ? alignBenchmark(points, benchmarkData.points)
        : null,
    [points, benchmarkData],
  );

  useEffect(() => {
    if (!containerRef.current || points.length === 0) return;
    let cancelled = false;

    void import("echarts").then((echarts) => {
      if (cancelled || !containerRef.current) return;
      const chart = chartInstanceRef.current ?? echarts.init(containerRef.current);
      chartInstanceRef.current = chart;
      chart.setOption(buildChartOption(points, benchmarkData, alignedBenchmark, isDark), {
        notMerge: true,
      });
    });

    return () => {
      cancelled = true;
    };
  }, [points, benchmarkData, alignedBenchmark, isDark]);

  useEffect(() => {
    function handleResize() {
      chartInstanceRef.current?.resize();
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    return () => {
      chartInstanceRef.current?.dispose();
      chartInstanceRef.current = null;
    };
  }, []);

  // Liczba przychodzi z backendu jako string policzony na `Decimal` — front
  // jej nie odtwarza (CLAUDE.md §8), tylko rozdziela znak od wartości do
  // wyświetlenia. `notice` niesie decyzję „czy oznaczyć dane jako przybliżone".
  const diff = benchmarkData?.outperformance ?? null;
  const notice = benchmarkNotice(benchmarkData);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          Wynik portfela (start = 100)
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-zinc-600 dark:text-zinc-400">
            <span>Porównaj z</span>
            <select
              value={benchmarkKey}
              onChange={(event) => setBenchmarkKey(event.target.value as BenchmarkKey | "none")}
              className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-800 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
            >
              {BENCHMARK_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
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
      </div>

      {performanceQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie wykresu wyników"
          className="h-64 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      )}

      {performanceQuery.isError && (
        <ErrorState
          message={
            performanceQuery.error instanceof ApiError
              ? performanceQuery.error.message
              : "Nie udało się wczytać wyników portfela."
          }
          onRetry={() => void performanceQuery.refetch()}
        />
      )}

      {performanceQuery.isSuccess && points.length === 0 && (
        <EmptyState
          title="Brak historii wyceny dla tego zakresu"
          description="Wykres pojawi się, gdy worker EOD zapisze przynajmniej dwa snapshoty wyceny portfela. Spróbuj zakresu „Max”."
        />
      )}

      {performanceQuery.isSuccess && points.length > 0 && data && (
        <>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <div>
              <dt className="inline text-zinc-600 dark:text-zinc-400">Zwrot za okres: </dt>
              <dd className="inline font-medium text-zinc-900 dark:text-zinc-50">
                {data.period_return === null ? "brak danych" : pct(data.period_return)}
              </dd>
            </div>
            {diff !== null && (
              <div>
                <dt className="inline text-zinc-600 dark:text-zinc-400">
                  Względem benchmarku:{" "}
                </dt>
                <dd className="inline font-medium text-zinc-900 dark:text-zinc-50">
                  {/* „p.p.", nie „pkt": obie serie mają bazę 100, więc różnica
                      jest w punktach PROCENTOWYCH. „pkt" sugerowałoby punkty
                      indeksowe, czyli inną wielkość. */}
                  {diff.startsWith("-") ? "−" : "+"}
                  {decimal(diff.replace("-", ""))} p.p.
                </dd>
              </div>
            )}
          </dl>

          <div ref={containerRef} className="h-64 w-full sm:h-80" />

          {/* „Z ilu ogniw" jest częścią odpowiedzi na pytanie, ile ten zwrot
              znaczy — ta sama liczba z 40 i z 250 ogniw znaczy co innego
              (decyzja 6 planu etapu 8). */}
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Zwrot policzony z {data.links}{" "}
            {data.links === 1 ? "dnia" : "dni"} notowań
            {data.skipped_composition_change > 0 && (
              <>
                {" "}
                (pominięto {data.skipped_composition_change}{" "}
                {data.skipped_composition_change === 1 ? "dzień" : "dni"} zmiany składu portfela —
                dokupienie nie jest zyskiem)
              </>
            )}
            . Obie serie startują od 100 w dniu {data.first_date && formatDate(data.first_date)}.
          </p>

          {notice?.kind === "unavailable" && (
            <p
              role="status"
              className="rounded-md bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200"
            >
              Brak serii porównawczej: {notice.reason}
            </p>
          )}

          {notice?.kind === "approximate" && (
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              <strong>Dane przybliżone.</strong> {notice.note}
            </p>
          )}

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
                      Portfel
                    </th>
                    {benchmarkData !== null && benchmarkData.points.length > 0 && (
                      <th scope="col" className="py-1">
                        {benchmarkData.label}
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {points.map((point, position) => {
                    const benchmarkValue = alignedBenchmark?.[position] ?? null;
                    return (
                      <tr key={point.date}>
                        <td className="py-1 pr-2">{formatDate(point.date)}</td>
                        <td className="py-1 pr-2">{Number(point.index).toFixed(2)}</td>
                        {benchmarkData !== null && benchmarkData.points.length > 0 && (
                          <td className="py-1">
                            {benchmarkValue === null ? "—" : benchmarkValue.toFixed(2)}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
