"use client";

/**
 * Donut alokacji (plan krok 33) — forma dla wymiaru „klasa aktywów":
 * kilka koszyków, z których każdy ma własną tożsamość, a pytanie brzmi
 * „jaka część całości".
 *
 * Etykieta procentowa jest rysowana wprost na wycinku (tylko dla wycinków
 * ≥ 8%, inaczej na 375 px etykiety nachodzą na siebie), legenda niesie nazwy
 * koszyków, a tabela pod wykresem (`AllocationTable`) podaje dokładne kwoty.
 * Kolor nigdy nie jest jedynym nośnikiem informacji — to jest też „relief"
 * wymagany przez ostrzeżenie o kontraście palety w trybie jasnym
 * (`lib/chartPalette.ts`).
 */
import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import type { AllocationBucket, AllocationDimension } from "@/lib/analytics";
import { toChartSlices } from "@/lib/allocationLabels";
import { categoricalColors, chartChrome, otherColor } from "@/lib/chartPalette";
import { pln, pct } from "@/lib/money";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { EChart } from "@/components/charts/EChart";

type AllocationDonutProps = {
  buckets: AllocationBucket[];
  by: AllocationDimension;
};

/** Poniżej tego udziału etykieta na wycinku jest pomijana (kolizje na 375 px). */
const LABEL_MIN_WEIGHT = 0.08;

export function AllocationDonut({ buckets, by }: AllocationDonutProps) {
  const isDark = useIsDarkTheme();

  const option = useMemo<EChartsOption>(() => {
    const slices = toChartSlices(buckets, by);
    const colors = categoricalColors(slices.length, isDark);
    const chrome = chartChrome(isDark);

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const p = params as { dataIndex: number };
          const slice = slices[p.dataIndex];
          if (!slice) return "";
          return `${slice.label}<br/>${pln(String(slice.value))} · ${pct(String(slice.weight))}`;
        },
      },
      legend: {
        type: "scroll",
        bottom: 0,
        textStyle: { color: chrome.label },
        pageTextStyle: { color: chrome.label },
        pageIconColor: chrome.axis,
        pageIconInactiveColor: chrome.splitLine,
      },
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          center: ["50%", "45%"],
          avoidLabelOverlap: true,
          // 2 px szczeliny w kolorze powierzchni — segmenty czytają się jako
          // osobne, nie jako jedna plama (skill `dataviz`).
          itemStyle: { borderColor: chrome.surface, borderWidth: 2, borderRadius: 4 },
          label: {
            show: true,
            position: "inside",
            color: "#ffffff",
            fontSize: 11,
            formatter: (params: unknown) => {
              const p = params as { dataIndex: number };
              const slice = slices[p.dataIndex];
              if (!slice || slice.weight < LABEL_MIN_WEIGHT) return "";
              return pct(String(slice.weight));
            },
          },
          labelLine: { show: false },
          data: slices.map((slice, index) => ({
            name: slice.label,
            value: slice.value,
            itemStyle: { color: slice.isOther ? otherColor(isDark) : colors[index] },
          })),
        },
      ],
    };
  }, [buckets, by, isDark]);

  return <EChart option={option} ariaLabel="Wykres kołowy alokacji" className="h-64 w-full sm:h-80" />;
}
