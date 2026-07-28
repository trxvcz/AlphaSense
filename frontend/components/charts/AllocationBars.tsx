"use client";

/**
 * Poziome słupki alokacji (plan krok 33) — forma dla wymiarów „sektor" i
 * „geografia".
 *
 * Powód innej formy niż donut: tych koszyków bywa kilkanaście i mają długie
 * nazwy („Ameryka Północna", „Usługi komunalne"). Na kole nie mieszczą się
 * ani etykiety, ani porównanie sąsiadów; poziomy słupek daje pełną nazwę na
 * osi, porównywalną długość i rośnie w dół, czyli w kierunku, w którym strona
 * i tak się przewija na 375 px.
 *
 * To JEDNA seria, więc kolor nie niesie tożsamości (niesie ją etykieta osi) —
 * stąd jeden hue zamiast palety kategorialnej i brak legendy.
 */
import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import type { AllocationBucket, AllocationDimension } from "@/lib/analytics";
import { toChartSlices } from "@/lib/allocationLabels";
import { chartChrome, otherColor, singleSeriesColor } from "@/lib/chartPalette";
import { pln, pct, pctAxis } from "@/lib/money";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { EChart } from "@/components/charts/EChart";

type AllocationBarsProps = {
  buckets: AllocationBucket[];
  by: AllocationDimension;
};

/** Powyżej tylu koszyków reszta trafia do „Pozostałe" — wykres przestaje się mieścić na ekranie. */
const MAX_BARS = 12;
const ROW_HEIGHT_PX = 34;
const CHART_PADDING_PX = 48;

export function AllocationBars({ buckets, by }: AllocationBarsProps) {
  const isDark = useIsDarkTheme();

  const slices = useMemo(() => toChartSlices(buckets, by, MAX_BARS), [buckets, by]);

  const option = useMemo<EChartsOption>(() => {
    const chrome = chartChrome(isDark);
    const barColor = singleSeriesColor(isDark);
    // Oś kategorii ECharts rysuje pierwszy element na DOLE — odwracamy, żeby
    // największy udział był na górze, tam gdzie wzrok zaczyna czytać.
    const ordered = [...slices].reverse();

    return {
      backgroundColor: "transparent",
      grid: { left: 8, right: 56, top: 8, bottom: 24, containLabel: true },
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const p = params as { dataIndex: number };
          const slice = ordered[p.dataIndex];
          if (!slice) return "";
          return `${slice.label}<br/>${pln(String(slice.value))} · ${pct(String(slice.weight))}`;
        },
      },
      xAxis: {
        type: "value",
        // Podziałki bez miejsc po przecinku i rzadziej niż domyślnie — na
        // 375 px „0,0% 20,0% 40,0%…" zlewa się w jedną kreskę.
        splitNumber: 4,
        axisLabel: { color: chrome.axis, formatter: (value: number) => pctAxis(String(value)) },
        splitLine: { lineStyle: { color: chrome.splitLine } },
      },
      yAxis: {
        type: "category",
        data: ordered.map((slice) => slice.label),
        axisLabel: { color: chrome.axis },
        axisLine: { lineStyle: { color: chrome.splitLine } },
        axisTick: { show: false },
      },
      series: [
        {
          type: "bar",
          data: ordered.map((slice) => ({
            value: slice.weight,
            itemStyle: {
              color: slice.isOther ? otherColor(isDark) : barColor,
              // Zaokrąglony koniec słupka, płaska podstawa przy osi.
              borderRadius: [0, 4, 4, 0],
            },
          })),
          barMaxWidth: 20,
          label: {
            show: true,
            position: "right",
            color: chrome.label,
            fontSize: 11,
            formatter: (params: unknown) => {
              const p = params as { dataIndex: number };
              const slice = ordered[p.dataIndex];
              return slice ? pct(String(slice.weight)) : "";
            },
          },
        },
      ],
    };
  }, [slices, isDark]);

  return (
    <EChart
      option={option}
      ariaLabel="Wykres słupkowy alokacji"
      className="w-full"
      // Wysokość rośnie z liczbą koszyków — inaczej przy kilkunastu sektorach
      // słupki zlewają się w jedną kreskę.
      style={{ height: `${slices.length * ROW_HEIGHT_PX + CHART_PADDING_PX}px` }}
    />
  );
}
