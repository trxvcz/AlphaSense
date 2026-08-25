"use client";

/**
 * Wykres underwater (plan krok 41b) — dystans indeksu do dotychczasowego
 * szczytu, przez `EChart`.
 *
 * **Pytanie analityczne, na które odpowiada:** „jak głęboko i jak długo
 * portfel był pod kreską względem swojego najlepszego momentu?" Zwykły
 * wykres wartości pokazuje pierwsze, ale nie drugie — a to czas trwania
 * obsunięcia jest tym, co inwestor faktycznie przeżywa.
 *
 * Rysuje serię z `/risk` (indeks łańcuchowy), nie `value_pln`: wpłata
 * podnosi wartość portfela i wyglądałaby jak wyjście z obsunięcia (ADR-101).
 *
 * Dostępność (CLAUDE.md §21): głębokość niesie **pozycja na osi**, a kolor
 * jest tylko wzmocnieniem — czerwony nie jest jedynym kanałem informacji.
 * Pod wykresem stoi zdanie z liczbami i datami, czytelne dla czytnika ekranu.
 */
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import type { Drawdown, UnderwaterPoint } from "@/lib/risk";
import { pctAxis } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { EChart } from "@/components/charts/EChart";

type UnderwaterChartProps = {
  points: UnderwaterPoint[];
  maxDrawdown: Drawdown | null;
};

function buildOption(points: UnderwaterPoint[], isDark: boolean): EChartsOption {
  const axisColor = isDark ? "#a1a1aa" : "#52525b";
  const splitLineColor = isDark ? "#3f3f46" : "#e4e4e7";
  const lineColor = isDark ? "#fb923c" : "#c2410c";
  const areaColor = isDark ? "rgba(251,146,60,0.25)" : "rgba(194,65,12,0.18)";

  return {
    backgroundColor: "transparent",
    grid: { left: 8, right: 16, top: 16, bottom: 32, containLabel: true },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => pctAxis(String(value)),
    },
    xAxis: {
      type: "category",
      data: points.map((p) => p.date),
      axisLabel: { color: axisColor, formatter: (value: string) => formatDate(value) },
      axisLine: { lineStyle: { color: splitLineColor } },
    },
    yAxis: {
      type: "value",
      // `max: 0` — underwater z definicji nie wchodzi nad zero, a oś
      // sięgająca wyżej sugerowałaby, że mogłoby.
      max: 0,
      axisLabel: { color: axisColor, formatter: (value: number) => pctAxis(String(value)) },
      splitLine: { lineStyle: { color: splitLineColor } },
    },
    series: [
      {
        type: "line",
        name: "Poniżej szczytu",
        data: points.map((p) => Number(p.value)),
        showSymbol: false,
        lineStyle: { color: lineColor, width: 2 },
        areaStyle: { color: areaColor },
      },
    ],
  };
}

export function UnderwaterChart({ points, maxDrawdown }: UnderwaterChartProps) {
  const isDark = useIsDarkTheme();
  const option = useMemo(() => buildOption(points, isDark), [points, isDark]);

  if (points.length === 0) return null;

  return (
    <div>
      <EChart
        option={option}
        ariaLabel="Wykres underwater — jak głęboko portfel stoi poniżej swojego dotychczasowego szczytu"
        className="h-56 w-full"
      />
      {maxDrawdown !== null && (
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Największe obsunięcie: <strong>{pctAxis(maxDrawdown.value)}</strong> od{" "}
          {formatDate(maxDrawdown.peak_date)} do {formatDate(maxDrawdown.trough_date)}.{" "}
          {maxDrawdown.recovered_at === null
            ? "Jeszcze nieodrobione."
            : `Odrobione ${formatDate(maxDrawdown.recovered_at)}.`}
        </p>
      )}
    </div>
  );
}
