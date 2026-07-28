"use client";

/**
 * Treemapa alokacji (plan krok 33) — forma dla wymiaru „waluta".
 *
 * Powód innej formy niż donut: przy walutach interesuje nas przede wszystkim
 * dominacja jednej ekspozycji nad resztą (ile portfela realnie stoi w PLN, a
 * ile w obcej walucie), a prostokąt o polu proporcjonalnym do wartości czyta
 * się w tym pytaniu lepiej niż wycinek koła — i mieści etykietę razem z
 * procentem wprost na kafelku, bez legendy zjadającej wysokość na 375 px.
 */
import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import type { AllocationBucket, AllocationDimension } from "@/lib/analytics";
import { toChartSlices } from "@/lib/allocationLabels";
import { categoricalColors, chartChrome, otherColor } from "@/lib/chartPalette";
import { pln, pct } from "@/lib/money";
import { useIsDarkTheme } from "@/lib/useIsDarkTheme";
import { EChart } from "@/components/charts/EChart";

type AllocationTreemapProps = {
  buckets: AllocationBucket[];
  by: AllocationDimension;
};

export function AllocationTreemap({ buckets, by }: AllocationTreemapProps) {
  const isDark = useIsDarkTheme();

  const option = useMemo<EChartsOption>(() => {
    const slices = toChartSlices(buckets, by);
    const colors = categoricalColors(slices.length, isDark);
    const chrome = chartChrome(isDark);

    return {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (params: unknown) => {
          const p = params as { data?: { sliceIndex?: number } };
          const slice = p.data?.sliceIndex !== undefined ? slices[p.data.sliceIndex] : undefined;
          if (!slice) return "";
          return `${slice.label}<br/>${pln(String(slice.value))} · ${pct(String(slice.weight))}`;
        },
      },
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          // 2 px szczeliny w kolorze powierzchni (skill `dataviz`).
          itemStyle: { borderColor: chrome.surface, borderWidth: 2, gapWidth: 2, borderRadius: 4 },
          label: {
            show: true,
            color: "#ffffff",
            // 11 px, nie 12: przy dwóch–trzech koszykach jeden kafelek bywa
            // wąski i ECharts ucinał mu procent do „19,…”.
            fontSize: 11,
            lineHeight: 15,
            overflow: "break",
            formatter: (params: unknown) => {
              const p = params as { data?: { sliceIndex?: number } };
              const slice =
                p.data?.sliceIndex !== undefined ? slices[p.data.sliceIndex] : undefined;
              if (!slice) return "";
              return `${slice.label}\n${pct(String(slice.weight))}`;
            },
          },
          data: slices.map((slice, index) => ({
            name: slice.label,
            value: slice.value,
            sliceIndex: index,
            itemStyle: { color: slice.isOther ? otherColor(isDark) : colors[index] },
          })),
        },
      ],
    };
  }, [buckets, by, isDark]);

  return <EChart option={option} ariaLabel="Treemapa alokacji" className="h-64 w-full sm:h-80" />;
}
