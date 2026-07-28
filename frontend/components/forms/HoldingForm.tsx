"use client";

/**
 * Formularz dodawania pozycji (plan krok 35) — mobile first, 375 px.
 *
 * Kolejność pól odpowiada kolejności decyzji użytkownika: najpierw CO
 * (autouzupełnianie tickera z `GET /assets/search`, debounce 300 ms), potem
 * ILE (`inputMode="decimal"` — klawiatura numeryczna na telefonie), na końcu
 * opcjonalna cena nabycia. Cena jest jawnie oznaczona jako opcjonalna, bo
 * sercem produktu jest struktura portfela, a nie księgowość (CLAUDE.md #1) —
 * wymaganie jej odstraszałoby od dodania pierwszej pozycji.
 *
 * Kwoty i ilości jadą do API jako STRINGI, dokładnie tak, jak je wpisano —
 * żadnego `parseFloat` po drodze (CLAUDE.md #3.1). Jedyna walidacja liczb tu
 * na miejscu to kształt zapisu; ostatecznym sędzią jest backend (422).
 */
import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { ASSET_SEARCH_MIN_LENGTH, searchAssets, type AssetSearchResult } from "@/lib/assets";
import { createHolding } from "@/lib/dashboard";
import { qk } from "@/lib/queryKeys";
import { useDebounced } from "@/lib/useDebounced";

type HoldingFormProps = {
  portfolioId: string;
  onAdded?: () => void;
  onCancel?: () => void;
};

const SEARCH_DEBOUNCE_MS = 300;

/** Liczba dziesiętna w zapisie, jaki przyjmuje backend (`Decimal`). */
const DECIMAL_PATTERN = /^\d+(\.\d+)?$/;

/** Przecinek to naturalny separator na polskiej klawiaturze; API chce kropki. */
function normalizeDecimal(raw: string): string {
  return raw.trim().replace(",", ".");
}

export function HoldingForm({ portfolioId, onAdded, onCancel }: HoldingFormProps) {
  const fieldId = useId();
  const queryClient = useQueryClient();

  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AssetSearchResult | null>(null);
  const [quantity, setQuantity] = useState("");
  const [avgCost, setAvgCost] = useState("");
  const [costCurrency, setCostCurrency] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const debouncedQuery = useDebounced(query, SEARCH_DEBOUNCE_MS);
  const searchEnabled = !selected && debouncedQuery.trim().length >= ASSET_SEARCH_MIN_LENGTH;

  const searchQuery = useQuery({
    queryKey: qk.assetSearch(debouncedQuery.trim()),
    queryFn: () => searchAssets(debouncedQuery.trim()),
    enabled: searchEnabled,
  });

  const createMutation = useMutation({
    mutationFn: (input: Parameters<typeof createHolding>[1]) =>
      createHolding(portfolioId, input),
    onSuccess: async () => {
      // Dodanie pozycji zmienia WSZYSTKO, co zależy od składu portfela:
      // listę pozycji, podsumowanie, serię wycen i `holdings_version` samego
      // portfela (bumpowany przez backend w tej samej transakcji).
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.holdings(portfolioId) }),
        queryClient.invalidateQueries({ queryKey: qk.summary(portfolioId) }),
        queryClient.invalidateQueries({ queryKey: qk.portfolio(portfolioId) }),
        // Bez `range` w kluczu — unieważnia serię dla każdego zakresu naraz.
        queryClient.invalidateQueries({ queryKey: ["valuations", portfolioId] }),
      ]);
      setQuery("");
      setSelected(null);
      setQuantity("");
      setAvgCost("");
      setCostCurrency("");
      setFormError(null);
      onAdded?.();
    },
  });

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setFormError(null);

    if (!selected) {
      setFormError("Wybierz aktywo z listy podpowiedzi.");
      return;
    }

    const normalizedQuantity = normalizeDecimal(quantity);
    if (!DECIMAL_PATTERN.test(normalizedQuantity)) {
      setFormError("Ilość musi być liczbą dodatnią, np. 10 albo 0.5.");
      return;
    }

    const normalizedCost = normalizeDecimal(avgCost);
    const hasCost = normalizedCost.length > 0;
    if (hasCost && !DECIMAL_PATTERN.test(normalizedCost)) {
      setFormError("Cena nabycia musi być liczbą, np. 123.45.");
      return;
    }
    const currency = costCurrency.trim().toUpperCase();
    if (hasCost && !/^[A-Z]{3}$/.test(currency)) {
      setFormError("Podaj trzyliterowy kod waluty ceny nabycia, np. PLN.");
      return;
    }

    createMutation.mutate({
      asset_id: selected.id,
      quantity: normalizedQuantity,
      ...(hasCost ? { avg_cost: normalizedCost, cost_currency: currency } : {}),
    });
  }

  const results = searchQuery.data ?? [];
  const submitError =
    createMutation.error instanceof ApiError
      ? createMutation.error.message
      : createMutation.isError
        ? "Nie udało się dodać pozycji."
        : null;
  const errorMessage = formError ?? submitError;

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
    >
      <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Dodaj pozycję
      </h2>

      {/* --- Aktywo --- */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor={`${fieldId}-asset`}
          className="text-sm font-medium text-zinc-700 dark:text-zinc-300"
        >
          Aktywo
        </label>
        {selected ? (
          <div className="flex items-center justify-between gap-2 rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700">
            <span className="min-w-0 text-sm text-zinc-900 dark:text-zinc-50">
              <span className="font-medium">{selected.symbol}</span>{" "}
              <span className="text-zinc-600 dark:text-zinc-400">{selected.name}</span>
            </span>
            <button
              type="button"
              onClick={() => {
                setSelected(null);
                setQuery("");
              }}
              className="shrink-0 rounded-md px-2 py-1 text-sm text-blue-700 outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              Zmień
            </button>
          </div>
        ) : (
          <>
            <input
              id={`${fieldId}-asset`}
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Wpisz ticker lub nazwę, np. CDR"
              autoComplete="off"
              role="combobox"
              aria-expanded={results.length > 0}
              aria-controls={`${fieldId}-asset-results`}
              className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
            {searchEnabled && (
              <ul
                id={`${fieldId}-asset-results`}
                role="listbox"
                aria-label="Wyniki wyszukiwania aktywa"
                className="max-h-56 overflow-y-auto rounded-md border border-zinc-200 dark:border-zinc-800"
              >
                {searchQuery.isLoading && (
                  <li className="px-3 py-2 text-sm text-zinc-600 dark:text-zinc-400">
                    Szukam…
                  </li>
                )}
                {searchQuery.isError && (
                  <li className="px-3 py-2 text-sm text-red-600 dark:text-red-400">
                    Nie udało się wyszukać aktywa.
                  </li>
                )}
                {searchQuery.isSuccess && results.length === 0 && (
                  <li className="px-3 py-2 text-sm text-zinc-600 dark:text-zinc-400">
                    Brak trafień dla „{debouncedQuery.trim()}&rdquo;.
                  </li>
                )}
                {results.map((asset) => (
                  <li key={asset.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={false}
                      onClick={() => {
                        setSelected(asset);
                        setQuery("");
                      }}
                      className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left outline-offset-2 hover:bg-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:hover:bg-zinc-800"
                    >
                      <span className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                        {asset.symbol}
                      </span>
                      <span className="text-xs text-zinc-600 dark:text-zinc-400">
                        {asset.name}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {/* --- Ilość --- */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor={`${fieldId}-quantity`}
          className="text-sm font-medium text-zinc-700 dark:text-zinc-300"
        >
          Ilość
        </label>
        <input
          id={`${fieldId}-quantity`}
          type="text"
          // `inputMode` zamiast `type="number"`: na telefonie daje klawiaturę
          // numeryczną, ale nie dokłada strzałek ani lokalnego parsowania
          // liczby przez przeglądarkę (chcemy string 1:1 dla backendu).
          inputMode="decimal"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          placeholder="np. 10"
          className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
      </div>

      {/* --- Cena nabycia (opcjonalna) --- */}
      <fieldset className="flex flex-col gap-2 rounded-md border border-dashed border-zinc-300 p-3 dark:border-zinc-700">
        <legend className="px-1 text-xs text-zinc-600 dark:text-zinc-400">
          Cena nabycia — opcjonalna, potrzebna tylko do wyniku pozycji
        </legend>
        <div className="flex gap-2">
          <div className="flex flex-1 flex-col gap-1">
            <label
              htmlFor={`${fieldId}-avg-cost`}
              className="text-sm font-medium text-zinc-700 dark:text-zinc-300"
            >
              Średnia cena
            </label>
            <input
              id={`${fieldId}-avg-cost`}
              type="text"
              inputMode="decimal"
              value={avgCost}
              onChange={(event) => setAvgCost(event.target.value)}
              placeholder="np. 123.45"
              className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
          </div>
          <div className="flex w-24 flex-col gap-1">
            <label
              htmlFor={`${fieldId}-cost-currency`}
              className="text-sm font-medium text-zinc-700 dark:text-zinc-300"
            >
              Waluta
            </label>
            <input
              id={`${fieldId}-cost-currency`}
              type="text"
              value={costCurrency}
              onChange={(event) => setCostCurrency(event.target.value)}
              placeholder="PLN"
              maxLength={3}
              autoCapitalize="characters"
              className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm uppercase text-zinc-900 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
          </div>
        </div>
      </fieldset>

      {errorMessage && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {errorMessage}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={createMutation.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {createMutation.isPending ? "Dodawanie…" : "Dodaj pozycję"}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-4 py-2 text-sm font-medium text-zinc-700 outline-offset-2 hover:bg-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Anuluj
          </button>
        )}
      </div>
    </form>
  );
}
