/**
 * Jedno miejsce z kluczami zapytań TanStack Query.
 *
 * Widoki nie budują kluczy samodzielnie — importują je z `qk`, żeby
 * unieważnianie (invalidateQueries) po mutacjach (np. dodanie pozycji)
 * trafiało dokładnie w te same klucze co odczyt.
 *
 * Do rozbudowy w kolejnych etapach (allocation, markets, holdings, ...).
 */
export const qk = {
  summary: (portfolioId: string) => ["summary", portfolioId] as const,
  portfolios: () => ["portfolios"] as const,
  portfolio: (portfolioId: string) => ["portfolio", portfolioId] as const,
  holdings: (portfolioId: string) => ["holdings", portfolioId] as const,
  valuations: (portfolioId: string, range: string) =>
    ["valuations", portfolioId, range] as const,
};
