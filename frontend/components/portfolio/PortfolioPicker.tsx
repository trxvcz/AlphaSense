"use client";

/**
 * Wybór portfela dla tras z nawigacji głównej, które same portfela nie znają
 * (`/struktura` z kroku 33, `/rynki` z kroku 34).
 *
 * Przy jednym portfelu (typowy przypadek) nie ma czego wybierać — od razu
 * `replace` na widok docelowy, żeby kliknięcie w nawigacji nie kosztowało
 * użytkownika dodatkowego ekranu. `replace`, nie `push`, żeby „wstecz" nie
 * wracało na ten ekran przejściowy i nie odbijało z powrotem.
 *
 * Wydzielone przy kroku 34: obie trasy różnią się wyłącznie segmentem URL i
 * tekstami, a logika (przekierowanie, stan pusty, lista) jest ta sama.
 */
import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { listPortfolios } from "@/lib/portfolios";
import { qk } from "@/lib/queryKeys";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ListSkeleton } from "@/components/ui/ListSkeleton";

type PortfolioPickerProps = {
  /**
   * Segment docelowy: `/portfolios/{id}/{section}`. Pusty string prowadzi na
   * sam dashboard portfela (`/portfolios/{id}`), który nie ma własnego
   * segmentu — tak działa `/dashboard` z nawigacji.
   */
  section: string;
  title: string;
  description: string;
  /** Tekst stanu pustego — czym konkretnie jest widok, do którego nie ma jak wejść. */
  emptyDescription: string;
};

function targetHref(portfolioId: string, section: string): string {
  return section ? `/portfolios/${portfolioId}/${section}` : `/portfolios/${portfolioId}`;
}

export function PortfolioPicker({
  section,
  title,
  description,
  emptyDescription,
}: PortfolioPickerProps) {
  const router = useRouter();
  const portfoliosQuery = useQuery({
    queryKey: qk.portfolios(),
    queryFn: listPortfolios,
  });

  const portfolios = portfoliosQuery.data;
  const onlyPortfolioId = portfolios?.length === 1 ? portfolios[0]!.id : null;

  useEffect(() => {
    if (onlyPortfolioId) {
      router.replace(targetHref(onlyPortfolioId, section));
    }
  }, [onlyPortfolioId, router, section]);

  return (
    <section className="flex flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">{description}</p>
      </div>

      {(portfoliosQuery.isLoading || onlyPortfolioId !== null) && <ListSkeleton rows={2} />}

      {portfoliosQuery.isError && (
        <ErrorState
          message={
            portfoliosQuery.error instanceof ApiError
              ? portfoliosQuery.error.message
              : "Nie udało się wczytać portfeli."
          }
          onRetry={() => void portfoliosQuery.refetch()}
        />
      )}

      {portfolios?.length === 0 && (
        <EmptyState
          title="Nie masz jeszcze żadnego portfela"
          description={emptyDescription}
          action={
            <Link
              href="/portfolios"
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600"
            >
              Utwórz portfel
            </Link>
          }
        />
      )}

      {portfolios !== undefined && portfolios.length > 1 && (
        <ul className="flex flex-col gap-2">
          {portfolios.map((portfolio) => (
            <li key={portfolio.id}>
              <Link
                href={targetHref(portfolio.id, section)}
                className="flex items-center justify-between rounded-lg border border-zinc-200 px-4 py-3 outline-offset-2 hover:bg-zinc-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-800 dark:hover:bg-zinc-900"
              >
                <span className="font-medium text-zinc-900 dark:text-zinc-50">
                  {portfolio.name}
                </span>
                <span className="text-sm text-zinc-600 dark:text-zinc-400">{portfolio.type}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
