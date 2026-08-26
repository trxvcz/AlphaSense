"use client";

/**
 * Wykres świecowy (plan krok 45) — Lightweight Charts, jedyne miejsce
 * w aplikacji, które tej biblioteki dotyka.
 *
 * **Dlaczego nie ECharts, skoro reszta wykresów jest na ECharts:** stack
 * z CLAUDE.md §2 przewiduje dokładnie ten podział („ECharts — portfel,
 * struktura; Lightweight Charts — świece"). Powód jest praktyczny:
 * przewijanie i skalowanie osi czasu na dotyku, czyli to, po co w ogóle
 * ogląda się świece, jest tu wbudowane i lekkie.
 *
 * `import("lightweight-charts")` dynamicznie w `useEffect`, jak `EChart`
 * (krok 33): biblioteka sięga do `window`/`canvas` i nie renderuje się na
 * serwerze.
 *
 * **Dostępność (CLAUDE.md §21):** kierunek świecy niosą kolor **i** pozycja
 * korpusu, a pod wykresem stoi zdanie z konkretnymi liczbami — kanwas jest
 * dla czytnika ekranu pusty, więc bez tego opisu wykres nie mówi nic.
 */
import { useEffect, useRef } from "react";

import type { ChartCandle } from "@/lib/candles";

type CandleChartProps = {
  candles: ChartCandle[];
  /** Opis wykresu dla czytnika ekranu — sam kanwas jest dla niego pusty. */
  ariaLabel: string;
  isDark: boolean;
};

export function CandleChart({ candles, ariaLabel, isDark }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    let dispose: (() => void) | undefined;

    void (async () => {
      const { createChart, CandlestickSeries, ColorType } = await import("lightweight-charts");
      if (cancelled || !containerRef.current) return;

      const chart = createChart(containerRef.current, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: isDark ? "#a1a1aa" : "#52525b",
        },
        grid: {
          vertLines: { color: isDark ? "#27272a" : "#e4e4e7" },
          horzLines: { color: isDark ? "#27272a" : "#e4e4e7" },
        },
        rightPriceScale: { borderColor: isDark ? "#3f3f46" : "#d4d4d8" },
        timeScale: { borderColor: isDark ? "#3f3f46" : "#d4d4d8" },
      });

      const series = chart.addSeries(CandlestickSeries, {
        // Zieleń/czerwień to konwencja rynkowa i tu zostaje, ale NIE jest
        // jedynym kanałem: kierunek widać z położenia korpusu, a liczby
        // stoją w opisie pod wykresem.
        upColor: "#16a34a",
        downColor: "#dc2626",
        borderUpColor: "#16a34a",
        borderDownColor: "#dc2626",
        wickUpColor: "#16a34a",
        wickDownColor: "#dc2626",
      });
      series.setData(candles);
      chart.timeScale().fitContent();

      dispose = () => chart.remove();
    })();

    return () => {
      cancelled = true;
      dispose?.();
    };
  }, [candles, isDark]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={ariaLabel}
      className="h-72 w-full"
    />
  );
}
