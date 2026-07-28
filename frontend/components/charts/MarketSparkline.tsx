"use client";

/**
 * Sparkline indeksu referencyjnego (plan krok 34) — do 30 ostatnich notowań
 * `close_adj` w wierszu rankingu rynków.
 *
 * Bez osi, siatki i etykiet: to nie jest wykres do odczytywania wartości
 * (od tego jest liczba obok), tylko kształt ostatnich tygodni. Dokładne
 * liczby są w tooltipie i w tabeli pod panelem.
 *
 * Linia jest CELOWO neutralna (jeden kolor serii), a nie zielona/czerwona wg
 * `change_1d`: seria pokazuje 30 notowań, a `change_1d` to zmiana z jednego
 * dnia — pomalowanie miesiąca kolorem ostatniej sesji sugerowałoby trend,
 * którego ten kolor nie opisuje. Znak zmiany niesie liczba obok
 * (`changeColorClass`).
 */
import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import type { PricePoint } from "@/lib/analytics";
import { singleSeriesColor } from "@/lib/chartPalette";
import { decimal } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { EChart } from "@/components/charts/EChart";

type MarketSparklineProps = {
  series: PricePoint[];
  /** Symbol indeksu — trafia do opisu dla czytnika ekranu. */
  symbol: string;
};

export function MarketSparkline({ series, symbol }: MarketSparklineProps) {
  const isDark = useIsDarkTheme();

  const option = useMemo<EChartsOption>(() => {
    const lineColor = singleSeriesColor(isDark);

    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 2, right: 2, top: 4, bottom: 4 },
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params];
          const first = list[0] as { dataIndex?: number } | undefined;
          if (!first || typeof first.dataIndex !== "number") return "";
          const point = series[first.dataIndex];
          if (!point) return "";
          return `${formatDate(point.date)}<br/>${decimal(point.close_adj)}`;
        },
      },
      xAxis: { type: "category", show: false, data: series.map((p) => p.date), boundaryGap: false },
      // `min: "dataMin"` — sparkline ma pokazać kształt zmian, a oś od zera
      // spłaszczyłaby indeks o wartości kilkudziesięciu tysięcy do prostej.
      yAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
      series: [
        {
          type: "line",
          data: series.map((p) => Number(p.close_adj)),
          symbol: "none",
          smooth: false,
          lineStyle: { color: lineColor, width: 2 },
          areaStyle: {
            color: isDark ? "rgba(57,135,229,0.20)" : "rgba(42,120,214,0.12)",
          },
        },
      ],
    };
  }, [series, isDark]);

  return (
    <EChart
      option={option}
      ariaLabel={`Notowania indeksu ${symbol} z ostatnich ${series.length} sesji`}
      className="h-10 w-full"
    />
  );
}
