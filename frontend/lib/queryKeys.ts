/**
 * Jedno miejsce z kluczami zapytań TanStack Query.
 *
 * Widoki nie budują kluczy samodzielnie — importują je z `qk`, żeby
 * unieważnianie (invalidateQueries) po mutacjach (np. dodanie pozycji)
 * trafiało dokładnie w te same klucze co odczyt.
 *
 * Do rozbudowy w kolejnych etapach (markets, ...).
 */
import type { AllocationDimension } from "@/lib/analytics";

export const qk = {
  summary: (portfolioId: string) => ["summary", portfolioId] as const,
  portfolios: () => ["portfolios"] as const,
  portfolio: (portfolioId: string) => ["portfolio", portfolioId] as const,
  holdings: (portfolioId: string) => ["holdings", portfolioId] as const,
  valuations: (portfolioId: string, range: string) =>
    ["valuations", portfolioId, range] as const,
  assetSearch: (query: string) => ["assetSearch", query] as const,
  allocation: (portfolioId: string, by: AllocationDimension) =>
    ["allocation", portfolioId, by] as const,
  concentration: (portfolioId: string) => ["concentration", portfolioId] as const,
  // `range` i `benchmark` są CZĘŚCIĄ klucza: obie zawężają/rozszerzają zasób
  // po stronie API (inne okno, druga seria), więc odpowiedzi nie są
  // wymienne. Ta sama zasada co przy `news` niżej.
  performance: (portfolioId: string, range: string, benchmark: string | null) =>
    ["performance", portfolioId, range, benchmark ?? "none"] as const,
  markets: (portfolioId: string) => ["markets", portfolioId] as const,
  // `withSentimentOnly` jest CZĘŚCIĄ klucza, nie parametrem odczytu: filtr
  // zawęża zbiór po stronie API, więc odpowiedzi z `true` i `false` to dwa
  // różne zasoby. Wspólny klucz pokazywałby po przełączeniu filtra dane
  // z poprzedniego zapytania jako świeże.
  news: (portfolioId: string, withSentimentOnly: boolean) =>
    ["news", portfolioId, withSentimentOnly] as const,
};
