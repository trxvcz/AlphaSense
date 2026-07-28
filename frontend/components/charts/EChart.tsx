"use client";

/**
 * Cienkie opakowanie na instancję ECharts (plan krok 33).
 *
 * Trzy wykresy struktury (donut, treemap, słupki) różnią się WYŁĄCZNIE
 * obiektem opcji — cykl życia instancji (dynamiczny `import("echarts")`,
 * `setOption`, resize okna, `dispose` przy odmontowaniu) jest w każdym z nich
 * identyczny, więc żyje tutaj zamiast być przepisany trzy razy.
 *
 * `import("echarts")` w `useEffect`, nie na górze modułu — ECharts sięga do
 * `window`/`canvas` i nie renderuje się na serwerze (CLAUDE.md sekcja 2:
 * „ECharts przez dynamiczny import").
 *
 * `ValueChart` (krok 32) świadomie NIE został przepisany na ten komponent —
 * działa, jest pokryty żywą weryfikacją, a przenoszenie go tutaj byłoby
 * refaktorem poza zakresem kroku 33 (CLAUDE.md sekcja 4.3).
 */
import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import type { EChartsOption } from "echarts";

type EChartProps = {
  option: EChartsOption;
  /** Opis wykresu dla czytnika ekranu — sam kanwas jest dla niego pusty. */
  ariaLabel: string;
  /** Wysokość/układ kontenera; wykres zawsze wypełnia go w 100%. */
  className?: string;
  /** Wysokość wyliczana w locie (słupki rosną z liczbą koszyków) — nie da się jej wyrazić klasą Tailwinda. */
  style?: CSSProperties;
};

export function EChart({ option, ariaLabel, className, style }: EChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<import("echarts").ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;

    void import("echarts").then((echarts) => {
      if (cancelled || !containerRef.current) return;
      const chart = chartRef.current ?? echarts.init(containerRef.current);
      chartRef.current = chart;
      // Wysokość kontenera bywa liczona z danych (słupki rosną z liczbą
      // koszyków) — `setOption` sam nie mierzy kontenera ponownie.
      chart.resize();
      // `notMerge` — przy zmianie wymiaru alokacji zmienia się typ serii
      // (pie → treemap → bar); scalanie opcji zostawiłoby resztki poprzedniej.
      chart.setOption(option, { notMerge: true });
    });

    return () => {
      cancelled = true;
    };
  }, [option]);

  // Mobile first: layout przełamuje się między 375 px a desktopem, kanwa
  // ECharts nie skaluje się sama.
  useEffect(() => {
    function handleResize() {
      chartRef.current?.resize();
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  return (
    <div ref={containerRef} role="img" aria-label={ariaLabel} className={className} style={style} />
  );
}
