"use client";

/**
 * Panel ryzyka portfela (plan krok 41b): zmienność, Sharpe, max drawdown
 * z wykresem underwater, beta i heatmapa zwrotów miesięcznych.
 *
 * **Zasada tego ekranu:** każda metryka, której nie da się policzyć,
 * pokazuje **powód**, a nie pustkę i nie zero. Powody przychodzą gotowe
 * z API (`*_unavailable_reason`) — front ich nie wymyśla, bo tylko backend
 * wie, czy zabrakło historii, czy stopy referencyjnej NBP (CLAUDE.md #3.15).
 *
 * `range` i `benchmark` są w kluczu zapytania, bo zawężają zasób po stronie
 * API — ta sama zasada co w `PerformanceChart`.
 *
 * Dostępność (CLAUDE.md §21): żadna informacja nie jest niesiona wyłącznie
 * kolorem. Kafelki mają podpisy, obsunięcie ma znak i daty w tekście,
 * heatmapa ma liczby w komórkach.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import type { ValuationRange } from "@/lib/dashboard";
import { BENCHMARK_OPTIONS, type BenchmarkKey } from "@/lib/performance";
import { getRisk } from "@/lib/risk";
import { qk } from "@/lib/queryKeys";
import { decimal, pct } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { ErrorState } from "@/components/ui/ErrorState";
import { UnderwaterChart } from "@/components/charts/UnderwaterChart";
import { MonthlyReturnsHeatmap } from "@/components/charts/MonthlyReturnsHeatmap";

type RiskPanelProps = {
  portfolioId: string;
};

const RANGE_OPTIONS: { value: ValuationRange; label: string }[] = [
  { value: "1M", label: "1M" },
  { value: "3M", label: "3M" },
  { value: "1Y", label: "1R" },
  { value: "YTD", label: "YTD" },
  { value: "max", label: "Max" },
];

type MetricProps = {
  label: string;
  /** Sformatowana wartość albo `null`, gdy metryki nie da się policzyć. */
  value: string | null;
  /** Zdanie z API wyjaśniające brak — pokazywane zamiast wartości. */
  reason: string | null;
  hint?: string | null;
};

function Metric({ label, value, reason, hint }: MetricProps) {
  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400">{label}</p>
      {value !== null ? (
        <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
          {value}
        </p>
      ) : (
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          {reason ?? "Brak danych."}
        </p>
      )}
      {hint !== null && hint !== undefined && (
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>
      )}
    </div>
  );
}

export function RiskPanel({ portfolioId }: RiskPanelProps) {
  const [range, setRange] = useState<ValuationRange>("1Y");
  const [benchmark, setBenchmark] = useState<BenchmarkKey | null>(null);

  const riskQuery = useQuery({
    queryKey: qk.risk(portfolioId, range, benchmark),
    queryFn: () => getRisk(portfolioId, range, benchmark),
  });

  if (riskQuery.isError) {
    return (
      <ErrorState
        message={
          riskQuery.error instanceof ApiError
            ? riskQuery.error.message
            : "Nie udało się wczytać metryk ryzyka."
        }
        onRetry={() => void riskQuery.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <div role="group" aria-label="Zakres" className="flex flex-wrap gap-1">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setRange(option.value)}
              aria-pressed={range === option.value}
              className={
                range === option.value
                  ? "rounded border border-blue-600 bg-blue-600 px-3 py-1 text-sm text-white"
                  : "rounded border border-zinc-300 px-3 py-1 text-sm text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
              }
            >
              {option.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
          Beta wobec:
          <select
            value={benchmark ?? "none"}
            onChange={(event) =>
              setBenchmark(event.target.value === "none" ? null : (event.target.value as BenchmarkKey))
            }
            className="rounded border border-zinc-300 bg-white px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
          >
            {BENCHMARK_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {riskQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie metryk ryzyka"
          className="h-64 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      )}

      {riskQuery.isSuccess && (
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {riskQuery.data.first_date === null || riskQuery.data.last_date === null
              ? "Portfel nie ma jeszcze historii wyceny."
              : `Okres ${formatDate(riskQuery.data.first_date)} – ${formatDate(
                  riskQuery.data.last_date,
                )}, ${riskQuery.data.observations} dni z wyceną (minimum ${
                  riskQuery.data.min_observations
                } dla metryk statystycznych).`}
          </p>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Metric
              label="Zmienność (roczna)"
              value={riskQuery.data.volatility === null ? null : pct(riskQuery.data.volatility)}
              reason={riskQuery.data.volatility_unavailable_reason}
            />
            <Metric
              label="Sharpe (roczny)"
              value={riskQuery.data.sharpe === null ? null : decimal(riskQuery.data.sharpe)}
              reason={riskQuery.data.sharpe_unavailable_reason}
              hint={riskQuery.data.risk_free_label}
            />
            <Metric
              label="Max drawdown"
              value={
                riskQuery.data.max_drawdown === null
                  ? null
                  : pct(riskQuery.data.max_drawdown.value)
              }
              reason="Portfel nie ma jeszcze historii wyceny."
            />
            {riskQuery.data.beta !== null && (
              <Metric
                label={`Beta wobec ${riskQuery.data.beta.label}`}
                value={
                  riskQuery.data.beta.value === null ? null : decimal(riskQuery.data.beta.value)
                }
                reason={riskQuery.data.beta.unavailable_reason}
                hint={
                  riskQuery.data.beta.approximate
                    ? `Liczone z ${riskQuery.data.beta.symbol} — wartość przybliżona.`
                    : null
                }
              />
            )}
          </div>

          <section className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
              Obsunięcia (underwater)
            </h2>
            {riskQuery.data.underwater.length === 0 ? (
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Brak historii wyceny — nie ma czego pokazać.
              </p>
            ) : (
              <UnderwaterChart
                points={riskQuery.data.underwater}
                maxDrawdown={riskQuery.data.max_drawdown}
              />
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
              Zwroty miesięczne
            </h2>
            <MonthlyReturnsHeatmap returns={riskQuery.data.monthly_returns} />
          </section>
        </>
      )}
    </div>
  );
}
