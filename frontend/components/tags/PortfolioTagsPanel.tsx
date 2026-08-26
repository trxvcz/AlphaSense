"use client";

/**
 * Zarządzanie tagami przy pozycjach portfela (plan krok 43b).
 *
 * **Tag wisi na aktywie, nie na pozycji** — otagowanie PKN w jednym portfelu
 * oznacza tę spółkę wszędzie u tego użytkownika. Panel mówi to wprost, bo
 * inaczej „tagi przy pozycji" sugerowałyby zakres jednego portfela.
 *
 * Mapę `aktywo → tagi` składamy z `GET /tags` + `GET /tags/{id}/assets`
 * (po jednym zapytaniu na tag, `useQueries`). Osobnego endpointu „tagi tego
 * aktywa" świadomie nie dokładamy: tagów użytkownika są jednostki, a nowy
 * kształt w kontrakcie kosztuje więcej niż kilka zapytań, które i tak siedzą
 * w cache TanStack Query.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Holding } from "@/lib/dashboard";
import { ApiError } from "@/lib/api";
import { attachTag, createTag, detachTag, getTagAssets, getTags, type Tag } from "@/lib/tags";
import { qk } from "@/lib/queryKeys";
import { ErrorState } from "@/components/ui/ErrorState";

type PortfolioTagsPanelProps = {
  holdings: Holding[];
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function PortfolioTagsPanel({ holdings }: PortfolioTagsPanelProps) {
  const queryClient = useQueryClient();
  const [newTagName, setNewTagName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const tagsQuery = useQuery({ queryKey: qk.tags(), queryFn: getTags });
  const tags: Tag[] = useMemo(() => tagsQuery.data ?? [], [tagsQuery.data]);

  const assetQueries = useQueries({
    queries: tags.map((tag) => ({
      queryKey: qk.tagAssets(tag.id),
      queryFn: () => getTagAssets(tag.id),
    })),
  });

  /** `asset_id` → zbiór `tag_id`. Budowane raz, nie per wiersz tabeli. */
  const tagIdsByAsset = useMemo(() => {
    const map = new Map<string, Set<string>>();
    tags.forEach((tag, index) => {
      const assets = assetQueries[index]?.data ?? [];
      for (const asset of assets) {
        const current = map.get(asset.id) ?? new Set<string>();
        current.add(tag.id);
        map.set(asset.id, current);
      }
    });
    return map;
  }, [tags, assetQueries]);

  const invalidate = async (tagId: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.tags() }),
      queryClient.invalidateQueries({ queryKey: qk.tagAssets(tagId) }),
      // Alokacja mogła być liczona z filtrem po tym tagu.
      queryClient.invalidateQueries({ queryKey: ["allocation"] }),
    ]);
  };

  const toggleMutation = useMutation({
    mutationFn: async (input: { tagId: string; assetId: string; attached: boolean }) => {
      if (input.attached) await detachTag(input.tagId, input.assetId);
      else await attachTag(input.tagId, input.assetId);
      return input.tagId;
    },
    onSuccess: (tagId) => void invalidate(tagId),
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => createTag({ name }),
    onSuccess: async () => {
      setNewTagName("");
      setFormError(null);
      await queryClient.invalidateQueries({ queryKey: qk.tags() });
    },
    onError: (error: unknown) => {
      // 409 (duplikat nazwy) to normalny wynik, nie awaria — komunikat
      // z backendu jest po polsku i mówi dokładnie, co się stało.
      setFormError(apiErrorMessage(error, "Nie udało się utworzyć tagu."));
    },
  });

  if (tagsQuery.isError) {
    return (
      <ErrorState
        message={apiErrorMessage(tagsQuery.error, "Nie udało się wczytać tagów.")}
        onRetry={() => void tagsQuery.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Tagi pozycji</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Tag opisuje <strong>spółkę</strong>, nie pozycję w tym portfelu — oznaczenie działa
          we wszystkich Twoich portfelach.
        </p>
      </div>

      <form
        className="flex flex-wrap items-start gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const name = newTagName.trim();
          if (!name) return;
          createMutation.mutate(name);
        }}
      >
        <label className="sr-only" htmlFor="new-tag-name">
          Nazwa nowego tagu
        </label>
        <input
          id="new-tag-name"
          value={newTagName}
          onChange={(event) => setNewTagName(event.target.value)}
          maxLength={60}
          placeholder="np. dywidendowe"
          className="rounded-md border border-zinc-300 px-2 py-1 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <button
          type="submit"
          disabled={createMutation.isPending || newTagName.trim() === ""}
          className="rounded-md bg-blue-600 px-3 py-1 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50"
        >
          Dodaj tag
        </button>
      </form>
      {formError && (
        <p role="alert" className="text-xs text-red-700 dark:text-red-400">
          {formError}
        </p>
      )}

      {tags.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Nie masz jeszcze żadnego tagu. Załóż pierwszy powyżej, a potem przypisz go do
          pozycji.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {holdings.map((holding) => {
            const assigned = tagIdsByAsset.get(holding.asset_id) ?? new Set<string>();
            return (
              <li
                key={holding.id}
                className="flex flex-wrap items-center gap-2 rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800"
              >
                <span className="min-w-16 font-medium">
                  <Link
                    href={`/assets/${holding.asset_id}`}
                    className="text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
                  >
                    {holding.symbol}
                  </Link>
                </span>
                <div
                  role="group"
                  aria-label={`Tagi aktywa ${holding.symbol}`}
                  className="flex flex-wrap gap-1"
                >
                  {tags.map((tag) => {
                    const attached = assigned.has(tag.id);
                    return (
                      <button
                        key={tag.id}
                        type="button"
                        aria-pressed={attached}
                        disabled={toggleMutation.isPending}
                        onClick={() =>
                          toggleMutation.mutate({
                            tagId: tag.id,
                            assetId: holding.asset_id,
                            attached,
                          })
                        }
                        className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50 ${
                          attached
                            ? "border-blue-600 bg-blue-600 font-medium text-white"
                            : "border-dashed border-zinc-300 text-zinc-500 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
                        }`}
                      >
                        {tag.color && (
                          <span
                            aria-hidden="true"
                            className="h-2 w-2 shrink-0 rounded-full"
                            style={{ backgroundColor: tag.color }}
                          />
                        )}
                        {/* Znak mówi to samo co kolor obramowania — kolor nie
                            jest jedynym kanałem informacji (CLAUDE.md §21). */}
                        <span aria-hidden="true">{attached ? "✓" : "+"}</span>
                        {tag.name}
                      </button>
                    );
                  })}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
