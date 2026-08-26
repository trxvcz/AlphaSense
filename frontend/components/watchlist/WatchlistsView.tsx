"use client";

/**
 * Widok list obserwowanych (plan krok 43b).
 *
 * **Lista obserwowanych to nie drugi portfel** (CLAUDE.md #3.11): nie ma tu
 * ilości, wyceny ani zwrotu i nie mogą się tu pojawić „przy okazji" —
 * obserwowanie nie jest posiadaniem. Widok mówi to wprost, żeby pusta kolumna
 * wartości nie wyglądała na brakujące dane.
 *
 * Aktywa dodajemy przez wyszukiwarkę słownika (`/assets/search`), ten sam
 * mechanizm co w `HoldingForm` — z `useDebounced`, bo każdy znak inaczej
 * generowałby zapytanie na literę.
 */
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { ASSET_SEARCH_MIN_LENGTH, searchAssets, type AssetSearchResult } from "@/lib/assets";
import {
  addWatchlistItem,
  createWatchlist,
  deleteWatchlist,
  getWatchlistItems,
  getWatchlists,
  removeWatchlistItem,
} from "@/lib/watchlists";
import { qk } from "@/lib/queryKeys";
import { formatDate } from "@/lib/dates";
import { useDebounced } from "@/lib/useDebounced";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

const SEARCH_DEBOUNCE_MS = 300;

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function WatchlistsView() {
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const listsQuery = useQuery({ queryKey: qk.watchlists(), queryFn: getWatchlists });
  const lists = listsQuery.data ?? [];
  // Jeśli nic nie wybrano (albo wybrana lista zniknęła), pokazujemy pierwszą —
  // ekran z listami i pustym prawym panelem nie odpowiadałby na żadne pytanie.
  const selectedId = activeId && lists.some((l) => l.id === activeId) ? activeId : lists[0]?.id;

  const itemsQuery = useQuery({
    queryKey: qk.watchlistItems(selectedId ?? ""),
    queryFn: () => getWatchlistItems(selectedId as string),
    enabled: selectedId !== undefined,
  });

  const debouncedQuery = useDebounced(query, SEARCH_DEBOUNCE_MS);
  const searchQuery = useQuery({
    queryKey: qk.assetSearch(debouncedQuery.trim()),
    queryFn: () => searchAssets(debouncedQuery.trim()),
    enabled: debouncedQuery.trim().length >= ASSET_SEARCH_MIN_LENGTH,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => createWatchlist(name),
    onSuccess: async (created) => {
      setNewName("");
      setFormError(null);
      setActiveId(created.id);
      await queryClient.invalidateQueries({ queryKey: qk.watchlists() });
    },
    // 409 (duplikat nazwy) to normalny wynik, nie awaria — backend oddaje
    // komunikat po polsku.
    onError: (error: unknown) =>
      setFormError(apiErrorMessage(error, "Nie udało się utworzyć listy.")),
  });

  const deleteMutation = useMutation({
    mutationFn: (watchlistId: string) => deleteWatchlist(watchlistId),
    onSuccess: async () => {
      setActiveId(null);
      await queryClient.invalidateQueries({ queryKey: qk.watchlists() });
    },
  });

  const addMutation = useMutation({
    mutationFn: (assetId: string) =>
      addWatchlistItem(selectedId as string, assetId, null),
    onSuccess: async () => {
      setQuery("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.watchlistItems(selectedId as string) }),
        queryClient.invalidateQueries({ queryKey: qk.watchlists() }),
      ]);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (assetId: string) => removeWatchlistItem(selectedId as string, assetId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.watchlistItems(selectedId as string) }),
        queryClient.invalidateQueries({ queryKey: qk.watchlists() }),
      ]);
    },
  });

  return (
    <section className="flex flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Listy obserwowanych
        </h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Spółki, które śledzisz, ale których nie masz w portfelu. Bez ilości i wyceny —
          obserwowanie nie jest posiadaniem.
        </p>
      </div>

      <form
        className="flex flex-wrap items-start gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const name = newName.trim();
          if (!name) return;
          createMutation.mutate(name);
        }}
      >
        <label className="sr-only" htmlFor="new-watchlist-name">
          Nazwa nowej listy
        </label>
        <input
          id="new-watchlist-name"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          maxLength={120}
          placeholder="np. Do obserwacji"
          className="rounded-md border border-zinc-300 px-2 py-1 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <button
          type="submit"
          disabled={createMutation.isPending || newName.trim() === ""}
          className="rounded-md bg-blue-600 px-3 py-1 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50"
        >
          Utwórz listę
        </button>
      </form>
      {formError && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {formError}
        </p>
      )}

      {listsQuery.isLoading && (
        <div
          role="status"
          aria-label="Ładowanie list"
          className="h-24 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      )}
      {listsQuery.isError && (
        <ErrorState
          message={apiErrorMessage(listsQuery.error, "Nie udało się wczytać list.")}
          onRetry={() => void listsQuery.refetch()}
        />
      )}

      {listsQuery.isSuccess && lists.length === 0 && (
        <EmptyState
          title="Nie masz jeszcze żadnej listy obserwowanych"
          description="Utwórz pierwszą listę powyżej, a potem dodaj do niej spółki, które chcesz śledzić."
        />
      )}

      {selectedId !== undefined && (
        <>
          <div role="group" aria-label="Twoje listy" className="flex flex-wrap gap-1">
            {lists.map((list) => (
              <button
                key={list.id}
                type="button"
                aria-pressed={list.id === selectedId}
                onClick={() => setActiveId(list.id)}
                className={`rounded-md px-2 py-1 text-xs font-medium outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 ${
                  list.id === selectedId
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                }`}
              >
                {list.name} <span className="font-normal opacity-70">({list.item_count})</span>
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Obserwowane spółki
              </h2>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(selectedId)}
                disabled={deleteMutation.isPending}
                className="text-xs text-red-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50 dark:text-red-400"
              >
                Usuń tę listę
              </button>
            </div>

            <div className="flex flex-col gap-1">
              <label
                htmlFor="watchlist-asset-search"
                className="text-xs text-zinc-600 dark:text-zinc-400"
              >
                Dodaj spółkę (min. {ASSET_SEARCH_MIN_LENGTH} znaki)
              </label>
              <input
                id="watchlist-asset-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="np. CDR"
                className="rounded-md border border-zinc-300 px-2 py-1 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
              {searchQuery.isSuccess && searchQuery.data.length > 0 && (
                <ul className="flex flex-col gap-1">
                  {searchQuery.data.map((asset: AssetSearchResult) => (
                    <li key={asset.id}>
                      <button
                        type="button"
                        onClick={() => addMutation.mutate(asset.id)}
                        disabled={addMutation.isPending}
                        className="w-full rounded-md border border-zinc-200 px-3 py-1.5 text-left text-sm outline-offset-2 hover:bg-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50 dark:border-zinc-800 dark:hover:bg-zinc-800"
                      >
                        <span className="font-medium">{asset.symbol}</span>{" "}
                        <span className="text-zinc-500 dark:text-zinc-400">{asset.name}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {itemsQuery.isLoading && (
              <div
                role="status"
                aria-label="Ładowanie pozycji listy"
                className="h-16 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
              />
            )}
            {itemsQuery.isError && (
              <ErrorState
                message={apiErrorMessage(itemsQuery.error, "Nie udało się wczytać listy.")}
                onRetry={() => void itemsQuery.refetch()}
              />
            )}
            {itemsQuery.isSuccess && itemsQuery.data.length === 0 && (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                Ta lista jest jeszcze pusta. Znajdź spółkę wyszukiwarką powyżej.
              </p>
            )}
            {itemsQuery.isSuccess && itemsQuery.data.length > 0 && (
              <ul className="flex flex-col gap-2">
                {itemsQuery.data.map((item) => (
                  <li
                    key={item.asset_id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800"
                  >
                    <div className="flex flex-col">
                      <span className="font-medium text-zinc-900 dark:text-zinc-50">
                        <Link
                          href={`/assets/${item.asset_id}`}
                          className="text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
                        >
                          {item.symbol}
                        </Link>{" "}
                        <span className="text-xs font-normal text-zinc-500 dark:text-zinc-400">
                          {item.market_code} · {item.currency}
                        </span>
                      </span>
                      <span className="text-xs text-zinc-500 dark:text-zinc-400">
                        {item.name}
                        {item.note ? ` — ${item.note}` : ""}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-zinc-500 dark:text-zinc-400">
                        dodano {formatDate(item.added_at.slice(0, 10))}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeMutation.mutate(item.asset_id)}
                        disabled={removeMutation.isPending}
                        className="text-xs text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50 dark:text-blue-400"
                      >
                        Usuń z listy
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
