"use client";

/**
 * Dashboard portfela (plan krok 32) — karta podsumowania, wykres wartości
 * (ECharts) i top ruchy dnia. Client Component: TanStack Query hooki żyją
 * tutaj (ten sam wzorzec co `app/portfolios/page.tsx`); `page.tsx` w tym
 * katalogu zostaje Server Component i tylko rozpakowuje `params`.
 */
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { getPortfolio } from "@/lib/portfolios";
import { getSummary, listHoldings } from "@/lib/dashboard";
import { qk } from "@/lib/queryKeys";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { SummaryCard } from "@/components/dashboard/SummaryCard";
import { TopMovers } from "@/components/dashboard/TopMovers";
import { ValueChart } from "@/components/charts/ValueChart";
import { HoldingForm } from "@/components/forms/HoldingForm";
import { HoldingsImport } from "@/components/forms/HoldingsImport";

type PortfolioDashboardProps = {
  portfolioId: string;
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function PortfolioDashboard({ portfolioId }: PortfolioDashboardProps) {
  // Formularz pozycji (krok 35) jest zwijany: na 375 px stale rozwinięty
  // spychałby wartość portfela i wykres poniżej zgięcia, a to one są powodem,
  // dla którego użytkownik tu wchodzi. W portfelu pustym rozwija go CTA ze
  // stanu pustego — tam formularz JEST najważniejszą treścią ekranu.
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isImportOpen, setIsImportOpen] = useState(false);

  const portfolioQuery = useQuery({
    queryKey: qk.portfolio(portfolioId),
    queryFn: () => getPortfolio(portfolioId),
  });

  const summaryQuery = useQuery({
    queryKey: qk.summary(portfolioId),
    queryFn: () => getSummary(portfolioId),
  });

  const holdingsQuery = useQuery({
    queryKey: qk.holdings(portfolioId),
    queryFn: () => listHoldings(portfolioId),
  });

  return (
    <section className="flex flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      {portfolioQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie"
          className="h-8 w-56 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800"
        />
      )}
      {portfolioQuery.isError && (
        <ErrorState
          message={apiErrorMessage(portfolioQuery.error, "Nie udało się wczytać portfela.")}
          onRetry={() => void portfolioQuery.refetch()}
        />
      )}
      {portfolioQuery.isSuccess && (
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            {portfolioQuery.data.name}
          </h1>
          {/* Wejścia w widoki struktury (krok 33), wyników (kroki 40/42), rynków (krok 34) i dywidend (krok 47) z
              kontekstem tego portfela — nawigacja globalna prowadzi na
              `/struktura` i `/rynki`, które muszą dopiero zapytać, o który
              portfel chodzi. */}
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <Link
              href={`/portfolios/${portfolioId}/struktura`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              Zobacz strukturę portfela →
            </Link>
            <Link
              href={`/portfolios/${portfolioId}/wyniki`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              Zobacz wyniki na tle rynku →
            </Link>
            <Link
              href={`/portfolios/${portfolioId}/ryzyko`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              Zobacz ryzyko portfela →
            </Link>
            <Link
              href={`/portfolios/${portfolioId}/dywidendy`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              Zobacz kalendarz dywidend →
            </Link>
            <Link
              href="/obserwowane"
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              Zobacz listy obserwowanych →
            </Link>
            <Link
              href={`/portfolios/${portfolioId}/rynki`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              Zobacz swoje rynki →
            </Link>
          </div>
        </div>
      )}

      {holdingsQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie pozycji"
          className="h-32 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      )}

      {holdingsQuery.isSuccess && holdingsQuery.data.length === 0 ? (
        isImportOpen ? (
          <HoldingsImport
            portfolioId={portfolioId}
            onCancel={() => setIsImportOpen(false)}
          />
        ) : isFormOpen ? (
          <HoldingForm
            portfolioId={portfolioId}
            onAdded={() => setIsFormOpen(false)}
            onCancel={() => setIsFormOpen(false)}
          />
        ) : (
          <EmptyState
            title="Ten portfel nie ma jeszcze żadnej pozycji"
            description="Dodaj pierwszą pozycję, żeby zobaczyć wartość, wykres i strukturę portfela."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsFormOpen(true)}
                  className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600"
                >
                  Dodaj pierwszą pozycję
                </button>
                <button
                  type="button"
                  onClick={() => setIsImportOpen(true)}
                  className="rounded-md border border-zinc-300 px-4 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700"
                >
                  Importuj z CSV
                </button>
              </div>
            }
          />
        )
      ) : holdingsQuery.isSuccess ? (
        <>
          {isImportOpen ? (
            <HoldingsImport
              portfolioId={portfolioId}
              onCancel={() => setIsImportOpen(false)}
            />
          ) : isFormOpen ? (
            <HoldingForm
              portfolioId={portfolioId}
              onAdded={() => setIsFormOpen(false)}
              onCancel={() => setIsFormOpen(false)}
            />
          ) : (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setIsFormOpen(true)}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600"
              >
                Dodaj pozycję
              </button>
              <button
                type="button"
                onClick={() => setIsImportOpen(true)}
                className="rounded-md border border-zinc-300 px-4 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700"
              >
                Importuj z CSV
              </button>
            </div>
          )}

          <div>
            {summaryQuery.isLoading && (
              <div
                role="status"
                aria-label="Ładowanie podsumowania"
                className="h-32 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
              />
            )}
            {summaryQuery.isError && (
              <ErrorState
                message={apiErrorMessage(summaryQuery.error, "Nie udało się wczytać podsumowania.")}
                onRetry={() => void summaryQuery.refetch()}
              />
            )}
            {summaryQuery.isSuccess && <SummaryCard summary={summaryQuery.data} />}
          </div>

          <ValueChart portfolioId={portfolioId} />

          <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
              Top ruchy dnia
            </h2>
            <TopMovers holdings={holdingsQuery.data} />
          </div>
        </>
      ) : holdingsQuery.isError ? (
        <ErrorState
          message={apiErrorMessage(holdingsQuery.error, "Nie udało się wczytać pozycji.")}
          onRetry={() => void holdingsQuery.refetch()}
        />
      ) : null}
    </section>
  );
}
