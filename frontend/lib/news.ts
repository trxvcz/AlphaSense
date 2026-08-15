/**
 * Dostęp do feedu newsów (`GET /portfolios/{id}/news`, krok 46, etap 9) —
 * jedyne miejsce, które woła `apiFetch` dla tego zasobu (docs/konwencje.md:
 * „Bez fetch rozsianego po komponentach").
 *
 * Kształt odpowiedzi 1:1 z `docs/api-kontrakt.md` i `news/schemas.py`.
 * `sentiment` to STRING dziesiętny albo `null`, nie `number` (CLAUDE.md #3.1)
 * — mimo że nie jest kwotą, bo `float` w JSON-ie gubi precyzję niezależnie
 * od jednostki.
 *
 * Poza typami i wywołaniem siedzą tu **czyste funkcje opisujące dane**
 * (`confidenceLabel`, `sentimentLabel`). Są tutaj, a nie w komponencie,
 * bo to jedyna logika tego widoku dająca się przetestować bez DOM-u —
 * `lib/news.test.ts` (wzorzec `lib/topMovers.ts` + `lib/topMovers.test.ts`).
 */
import { apiFetch } from "@/lib/api";

/**
 * Skąd wzięło się powiązanie newsu z aktywem.
 *
 * - `source` — podał je dostawca pytany o symbol (Finnhub `/company-news`,
 *   Alpha Vantage `ticker_sentiment`). To fakt.
 * - `heuristic` — dopasowanie polskiego tekstu po naszej stronie
 *   (`backend/app/modules/news/matching.py`). To przybliżenie.
 *
 * Rozróżnienie **musi** być widoczne w UI (CLAUDE.md #3.15). Union, a nie
 * `string`, żeby dorzucenie trzeciego rodzaju pewności w backendzie
 * wywaliło `tsc`, a nie po cichu wyrenderowało się jako brak oznaczenia.
 */
export type MatchConfidence = "source" | "heuristic";

export type NewsAssetRef = {
  symbol: string;
  match_confidence: MatchConfidence;
};

export type NewsItem = {
  id: string;
  title: string;
  url: string;
  /** Wydawca depeszy (`bankier.pl`, `Reuters`), nie nasz pośrednik. */
  source: string;
  /** ISO 8601 z offsetem — pełny moment publikacji, nie sama data. */
  published_at: string;
  summary: string | null;
  /** Liczba dziesiętna jako string, albo `null` = nikt nie oceniał. */
  sentiment: string | null;
  sentiment_source: string | null;
  /** Wyłącznie aktywa z portfela pytającego (zawężenie po stronie API). */
  assets: NewsAssetRef[];
};

export type NewsFeed = {
  items: NewsItem[];
  assets_covered: number;
  /** Symbole pozycji, o których feed nic nie ma — patrz `NewsFeedPanel`. */
  assets_without_news: string[];
};

export function getPortfolioNews(
  portfolioId: string,
  options: { withSentimentOnly?: boolean; limit?: number } = {},
): Promise<NewsFeed> {
  const params = new URLSearchParams();
  if (options.withSentimentOnly) params.set("with_sentiment_only", "true");
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  const query = params.toString();
  return apiFetch<NewsFeed>(`/portfolios/${portfolioId}/news${query ? `?${query}` : ""}`);
}

/** Opis pewności powiązania — tekst, bo sam kolor nie jest kanałem informacji. */
export function confidenceLabel(confidence: MatchConfidence): string {
  return confidence === "source" ? "potwierdzone przez źródło" : "dopasowanie automatyczne";
}

/**
 * Czy feed zawiera choć jedno powiązanie zgadnięte przez nas.
 *
 * Steruje wyświetleniem zbiorczej noty o przybliżeniu: nota przy feedzie
 * złożonym wyłącznie z powiązań od dostawcy byłaby ostrzeżeniem bez
 * przedmiotu i nauczyłaby ją ignorować.
 */
export function hasHeuristicMatches(items: NewsItem[]): boolean {
  return items.some((item) =>
    item.assets.some((asset) => asset.match_confidence === "heuristic"),
  );
}

/** Wydźwięk oceny — `null` gdy nikt nie oceniał (to NIE jest to samo co 0). */
export type SentimentTone = "positive" | "neutral" | "negative";

/**
 * Progi wzięte z definicji Alpha Vantage (`sentiment_score_definition`:
 * `x <= -0.15` bearish, `x >= 0.15` bullish, pomiędzy — neutral). Nie są
 * naszym wynalazkiem i nie wolno ich „poprawiać" pod wygląd wykresu:
 * opisują skalę dostawcy, nie naszą opinię o newsie.
 *
 * **`Number`, mimo konwencji „kwoty z API nie przez `Number`"** (`lib/money.ts`,
 * CLAUDE.md #8). Ta konwencja broni przed utratą precyzji w liczbie, którą
 * potem *wyświetlamy* albo *liczymy*. Tutaj wynik jest klasyfikacją do
 * jednego z trzech kubełków przy progach ±0,15, a wartości mieszczą się
 * w [-1, 1] — `double` reprezentuje je z zapasem kilkunastu rzędów wielkości
 * ponad to, co mogłoby przestawić wynik porównania. Samej liczby nigdzie
 * nie pokazujemy.
 */
export function sentimentTone(sentiment: string): SentimentTone {
  const value = Number(sentiment);
  if (value >= 0.15) return "positive";
  if (value <= -0.15) return "negative";
  return "neutral";
}

export function sentimentLabel(tone: SentimentTone): string {
  if (tone === "positive") return "wydźwięk pozytywny";
  if (tone === "negative") return "wydźwięk negatywny";
  return "wydźwięk neutralny";
}
