"use client";

/**
 * Filtr tagów nad widokiem struktury (plan krok 43b).
 *
 * **Chip pokazuje nazwę zawsze, kolor tylko obok niej** — kolor nigdy nie jest
 * jedynym nośnikiem informacji (CLAUDE.md §21), a stan wyboru niosą dodatkowo
 * `aria-pressed` i obramowanie, nie sam odcień tła.
 *
 * Wielokrotny wybór ma semantykę **OR** (suma), nie AND — tak liczy backend
 * (`tags/repository.asset_ids_for_tag_names`) i tak to jest opisane pod
 * chipami, żeby pusty wynik nie wyglądał na awarię filtra.
 */
import { useQuery } from "@tanstack/react-query";

import { getTags, toggleTag } from "@/lib/tags";
import { qk } from "@/lib/queryKeys";

type TagFilterBarProps = {
  selected: readonly string[];
  onChange: (next: string[]) => void;
};

export function TagFilterBar({ selected, onChange }: TagFilterBarProps) {
  const tagsQuery = useQuery({ queryKey: qk.tags(), queryFn: getTags });

  if (tagsQuery.isLoading) {
    return (
      <div
        role="status"
        aria-label="Ładowanie tagów"
        className="h-8 w-48 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800"
      />
    );
  }

  // Brak tagów nie jest błędem ani pustym stanem do straszenia komunikatem —
  // filtr po prostu nie ma czym filtrować, dopóki użytkownik nic nie oznaczy.
  if (!tagsQuery.isSuccess || tagsQuery.data.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      <div role="group" aria-label="Filtr tagów" className="flex flex-wrap items-center gap-1">
        {tagsQuery.data.map((tag) => {
          const isSelected = selected.includes(tag.name);
          return (
            <button
              key={tag.id}
              type="button"
              aria-pressed={isSelected}
              onClick={() => onChange(toggleTag(selected, tag.name))}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 ${
                isSelected
                  ? "border-blue-600 bg-blue-600 text-white"
                  : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
              }`}
            >
              {tag.color && (
                <span
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: tag.color }}
                />
              )}
              {tag.name}
              <span className="font-normal opacity-70">({tag.asset_count})</span>
            </button>
          );
        })}
        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="rounded-full px-2.5 py-1 text-xs font-medium text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
          >
            Wyczyść filtr
          </button>
        )}
      </div>
      {selected.length > 1 && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Kilka tagów naraz działa jak suma: pokazujemy pozycje oznaczone{" "}
          <strong>którymkolwiek</strong> z nich.
        </p>
      )}
      {selected.length > 0 && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Wagi liczone są w obrębie przefiltrowanych pozycji, więc sumują się do 100% dla
          tego wyboru, a nie dla całego portfela.
        </p>
      )}
    </div>
  );
}
