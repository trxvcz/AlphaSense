"use client";

/**
 * Dashboard portfela (plan krok 32) — karta podsumowania, wykres wartości
 * (ECharts) i top ruchy dnia. Client Component: TanStack Query hooki żyją
 * tutaj (ten sam wzorzec co `app/portfolios/page.tsx`); `page.tsx` w tym
 * katalogu zostaje Server Component i tylko rozpakowuje `params`.
 */
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

type PortfolioDashboardProps = {
  portfolioId: string;
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function PortfolioDashboard({ portfolioId }: PortfolioDashboardProps) {
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
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          {portfolioQuery.data.name}
        </h1>
      )}

      {holdingsQuery.isSuccess && holdingsQuery.data.length === 0 ? (
        <EmptyState
          title="Ten portfel nie ma jeszcze żadnej pozycji"
          description="Dodaj pierwszą pozycję, żeby zobaczyć wartość, wykres i strukturę portfela. Formularz dodawania pozycji pojawi się w kolejnym kroku."
          action={
            <button
              type="button"
              disabled
              title="Formularz dodawania pozycji — krok 35, jeszcze niedostępny"
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white opacity-60"
            >
              Dodaj pierwszą pozycję
            </button>
          }
        />
      ) : (
        <>
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
            {holdingsQuery.isLoading && (
              <div
                role="status"
                aria-label="Ładowanie top ruchów dnia"
                className="h-24 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
              />
            )}
            {holdingsQuery.isError && (
              <ErrorState
                message={apiErrorMessage(holdingsQuery.error, "Nie udało się wczytać pozycji.")}
                onRetry={() => void holdingsQuery.refetch()}
              />
            )}
            {holdingsQuery.isSuccess && <TopMovers holdings={holdingsQuery.data} />}
          </div>
        </>
      )}
    </section>
  );
}
