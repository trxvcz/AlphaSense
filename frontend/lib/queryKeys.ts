/**
 * Jedno miejsce z kluczami zapytań TanStack Query.
 *
 * Widoki nie budują kluczy samodzielnie — importują je z `qk`, żeby
 * unieważnianie (invalidateQueries) po mutacjach (np. dodanie pozycji)
 * trafiało dokładnie w te same klucze co odczyt.
 *
 * Szkielet na razie zawiera jeden przykład (podsumowanie portfela) —
 * do rozbudowy w kolejnych etapach (allocation, markets, holdings, ...).
 */
export const qk = {
  summary: (portfolioId: string) => ["summary", portfolioId] as const,
};
