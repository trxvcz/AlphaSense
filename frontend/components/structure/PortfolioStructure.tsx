"use client";

/**
 * Widok struktury portfela (plan krok 33) — jeden ekran z przełącznikiem
 * wymiaru, wykresem dobranym do tego wymiaru, tabelą i kartą koncentracji.
 *
 * Dlaczego jeden ekran z przełącznikiem, a nie cztery osobne trasy: to jest
 * jedno pytanie („z czego składa się mój portfel?") zadawane w czterech
 * ujęciach. Przełącznik pozwala porównać ujęcia bez utraty kontekstu i bez
 * czterech pozycji w nawigacji, na 375 px szczególnie.
 *
 * Forma wykresu zależy od wymiaru (uzasadnienia w komponentach wykresów):
 * klasa → donut, waluta → treemapa, sektor i geografia → poziome słupki.
 *
 * Client Component: hooki TanStack Query i stan przełącznika żyją tutaj, a
 * `page.tsx` zostaje Server Component i tylko rozpakowuje `params` — ten sam
 * wzorzec co `PortfolioDashboard` (krok 32).
 */
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { getAllocation, getConcentration, type AllocationDimension } from "@/lib/analytics";
import { DIMENSION_LABELS, DIMENSION_NOTES } from "@/lib/allocationLabels";
import { getPortfolio } from "@/lib/portfolios";
import { qk } from "@/lib/queryKeys";
import { formatDate } from "@/lib/dates";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { AllocationBars } from "@/components/charts/AllocationBars";
import { AllocationDonut } from "@/components/charts/AllocationDonut";
import { AllocationTreemap } from "@/components/charts/AllocationTreemap";
import { AllocationTable } from "@/components/structure/AllocationTable";
import { ConcentrationCard } from "@/components/structure/ConcentrationCard";

type PortfolioStructureProps = {
  portfolioId: string;
};

/**
 * Wymiary pokazywane w tym widoku. `market` istnieje w API, ale dostaje własny
 * panel z indeksami referencyjnymi w kroku 34 — nie dublujemy go tutaj.
 */
const DIMENSIONS: AllocationDimension[] = ["class", "sector", "geo", "currency"];

/**
 * Wymiar domyślny wybiera frontend — backend nie ma wartości domyślnej i na
 * brak `?by=` zwraca 422 (decyzja udokumentowana w `analytics/routes.py`).
 * „Klasa aktywów" jako pierwsze pytanie, bo odpowiada na najgrubszy podział
 * (akcje vs krypto vs surowce) i ma najmniej koszyków.
 */
const DEFAULT_DIMENSION: AllocationDimension = "class";

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function PortfolioStructure({ portfolioId }: PortfolioStructureProps) {
  const [dimension, setDimension] = useState<AllocationDimension>(DEFAULT_DIMENSION);

  const portfolioQuery = useQuery({
    queryKey: qk.portfolio(portfolioId),
    queryFn: () => getPortfolio(portfolioId),
  });

  const allocationQuery = useQuery({
    queryKey: qk.allocation(portfolioId, dimension),
    queryFn: () => getAllocation(portfolioId, dimension),
  });

  const concentrationQuery = useQuery({
    queryKey: qk.concentration(portfolioId),
    queryFn: () => getConcentration(portfolioId),
  });

  const allocation = allocationQuery.data;
  const isEmpty = allocation !== undefined && allocation.buckets.length === 0;
  const note = DIMENSION_NOTES[dimension];

  return (
    <section className="flex flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-1">
        {portfolioQuery.isLoading && (
          <div
            role="status"
            aria-label="Ładowanie"
            className="h-8 w-56 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800"
          />
        )}
        {portfolioQuery.isSuccess && (
          <>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Struktura — {portfolioQuery.data.name}
            </h1>
            <Link
              href={`/portfolios/${portfolioId}`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              ← Wróć do dashboardu portfela
            </Link>
          </>
        )}
        {portfolioQuery.isError && (
          <ErrorState
            message={apiErrorMessage(portfolioQuery.error, "Nie udało się wczytać portfela.")}
            onRetry={() => void portfolioQuery.refetch()}
          />
        )}
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Skład portfela wg wymiaru
          </h2>
          <div role="group" aria-label="Wymiar alokacji" className="flex flex-wrap gap-1">
            {DIMENSIONS.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={dimension === value}
                onClick={() => setDimension(value)}
                className={`rounded-md px-2 py-1 text-xs font-medium outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 ${
                  dimension === value
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                }`}
              >
                {DIMENSION_LABELS[value]}
              </button>
            ))}
          </div>
        </div>

        {allocationQuery.isLoading && (
          <div
            role="status"
            aria-label="Ładowanie alokacji"
            className="h-64 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
          />
        )}

        {allocationQuery.isError && (
          <ErrorState
            message={apiErrorMessage(allocationQuery.error, "Nie udało się wczytać alokacji.")}
            onRetry={() => void allocationQuery.refetch()}
          />
        )}

        {isEmpty && (
          <EmptyState
            title="Nie ma jeszcze czego rozłożyć na czynniki"
            description="Struktura pojawi się, gdy portfel będzie miał przynajmniej jedną pozycję z aktualną wyceną."
            action={
              <Link
                href={`/portfolios/${portfolioId}`}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600"
              >
                Dodaj pozycję
              </Link>
            }
          />
        )}

        {allocation !== undefined && !isEmpty && (
          <>
            {dimension === "class" && (
              <AllocationDonut buckets={allocation.buckets} by={dimension} />
            )}
            {dimension === "currency" && (
              <AllocationTreemap buckets={allocation.buckets} by={dimension} />
            )}
            {(dimension === "sector" || dimension === "geo") && (
              <AllocationBars buckets={allocation.buckets} by={dimension} />
            )}

            {allocation.approximate && (
              <p
                role="note"
                className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200"
              >
                Wartości przybliżone: w portfelu są ETF-y, a ich sektor i geografia to
                klasyfikacja całego funduszu, nie jego realnego składu.
              </p>
            )}

            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Dane z {formatDate(allocation.as_of)} (EOD).
              {note ? ` ${note}` : ""}
            </p>

            <details className="text-sm">
              <summary className="cursor-pointer text-zinc-600 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-400">
                Pokaż dane wykresu w formie tabeli
              </summary>
              <div className="mt-2 max-h-80 overflow-y-auto">
                <AllocationTable buckets={allocation.buckets} by={dimension} />
              </div>
            </details>
          </>
        )}
      </div>

      {concentrationQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie koncentracji"
          className="h-32 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      )}
      {concentrationQuery.isError && (
        <ErrorState
          message={apiErrorMessage(
            concentrationQuery.error,
            "Nie udało się wczytać koncentracji.",
          )}
          onRetry={() => void concentrationQuery.refetch()}
        />
      )}
      {concentrationQuery.isSuccess && concentrationQuery.data.count > 0 && (
        <ConcentrationCard concentration={concentrationQuery.data} />
      )}
    </section>
  );
}
