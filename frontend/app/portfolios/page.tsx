"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { createPortfolio, listPortfolios } from "@/lib/portfolios";
import { qk } from "@/lib/queryKeys";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ListSkeleton } from "@/components/ui/ListSkeleton";

const PORTFOLIO_TYPES = [
  { value: "standard", label: "Standardowy" },
  { value: "emerytalny", label: "Emerytalny" },
  { value: "obserwacyjny", label: "Obserwacyjny" },
] as const;

const dateFormatter = new Intl.DateTimeFormat("pl-PL", {
  dateStyle: "medium",
});

export default function PortfoliosPage() {
  const queryClient = useQueryClient();
  const portfoliosQuery = useQuery({
    queryKey: qk.portfolios(),
    queryFn: listPortfolios,
  });

  const [name, setName] = useState("");
  const [type, setType] = useState<string>(PORTFOLIO_TYPES[0].value);
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: createPortfolio,
    onSuccess: () => {
      setName("");
      setFormError(null);
      void queryClient.invalidateQueries({ queryKey: qk.portfolios() });
    },
    onError: (error: unknown) => {
      setFormError(
        error instanceof ApiError
          ? error.message
          : "Nie udało się utworzyć portfela. Spróbuj ponownie.",
      );
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim().length === 0) {
      setFormError("Podaj nazwę portfela.");
      return;
    }
    createMutation.mutate({ name: name.trim(), type });
  }

  return (
    <section className="flex flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Twoje portfele
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Wybierz portfel, żeby zobaczyć jego skład, albo utwórz nowy.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 sm:flex-row sm:items-end dark:border-zinc-800"
      >
        <div className="flex flex-1 flex-col gap-1">
          <label
            htmlFor="portfolio-name"
            className="text-sm font-medium text-zinc-700 dark:text-zinc-300"
          >
            Nazwa portfela
          </label>
          <input
            id="portfolio-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="np. Portfel emerytalny"
            className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label
            htmlFor="portfolio-type"
            className="text-sm font-medium text-zinc-700 dark:text-zinc-300"
          >
            Typ
          </label>
          <select
            id="portfolio-type"
            value={type}
            onChange={(event) => setType(event.target.value)}
            className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
          >
            {PORTFOLIO_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <button
          type="submit"
          disabled={createMutation.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {createMutation.isPending ? "Tworzenie…" : "Nowy portfel"}
        </button>
      </form>

      {formError && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {formError}
        </p>
      )}

      {portfoliosQuery.isLoading && <ListSkeleton rows={3} />}

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

      {portfoliosQuery.isSuccess && portfoliosQuery.data.length === 0 && (
        <EmptyState
          title="Nie masz jeszcze żadnego portfela"
          description="Utwórz pierwszy portfel powyżej, żeby zacząć dodawać pozycje."
        />
      )}

      {portfoliosQuery.isSuccess && portfoliosQuery.data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {portfoliosQuery.data.map((portfolio) => (
            <li key={portfolio.id}>
              <Link
                href={`/portfolios/${portfolio.id}`}
                className="flex items-center justify-between rounded-lg border border-zinc-200 px-4 py-3 outline-offset-2 hover:bg-zinc-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-800 dark:hover:bg-zinc-900"
              >
                <span className="flex flex-col">
                  <span className="font-medium text-zinc-900 dark:text-zinc-50">
                    {portfolio.name}
                  </span>
                  <span className="text-sm text-zinc-600 dark:text-zinc-400">
                    {portfolio.type} · utworzono{" "}
                    {dateFormatter.format(new Date(portfolio.created_at))}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
