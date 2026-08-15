/**
 * Testy czystej logiki feedu newsów (`lib/news.ts`, krok 46).
 *
 * Bez DOM-u i bez sieci — sprawdzane jest to, co decyduje, czy widok mówi
 * prawdę o danych: progi wydźwięku (skala dostawcy, nie nasza) i wykrycie
 * powiązań zgadniętych przez nas, które muszą zostać oznaczone
 * (CLAUDE.md #3.15).
 */
import { describe, expect, it } from "vitest";

import {
  confidenceLabel,
  hasHeuristicMatches,
  sentimentLabel,
  sentimentTone,
  type NewsItem,
} from "@/lib/news";

function item(overrides: Partial<NewsItem> = {}): NewsItem {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    title: "Depesza",
    url: "https://example.test/a",
    source: "bankier.pl",
    published_at: "2026-08-11T10:00:00+00:00",
    summary: null,
    sentiment: null,
    sentiment_source: null,
    assets: [],
    ...overrides,
  };
}

describe("sentimentTone", () => {
  // Progi z `sentiment_score_definition` Alpha Vantage: x <= -0.15 bearish,
  // x >= 0.15 bullish, pomiędzy neutral. Testy pilnują granic, bo to one
  // decydują o etykiecie widocznej dla użytkownika.
  it.each([
    ["0.15", "positive"],
    ["0.46933", "positive"],
    ["0.14999", "neutral"],
    ["0", "neutral"],
    ["-0.14999", "neutral"],
    ["-0.15", "negative"],
    ["-0.18118300", "negative"],
  ])("%s → %s", (sentiment, expected) => {
    expect(sentimentTone(sentiment)).toBe(expected);
  });

  it("czyta pełną precyzję stringa, nie obcina do liczby całkowitej", () => {
    // Sentyment przychodzi z API STRINGIEM (CLAUDE.md #3.1) — gdyby ktoś
    // podmienił `Number` na `parseInt`, wszystkie oceny spłaszczyłyby się
    // do zera i cały feed wyglądałby na neutralny.
    expect(sentimentTone("0.20000000")).toBe("positive");
  });
});

describe("sentimentLabel", () => {
  it("każdy wydźwięk ma opis słowny, nie tylko kolor", () => {
    // Kolor nie może być jedynym kanałem informacji (CLAUDE.md #3.21).
    expect(sentimentLabel("positive")).toContain("pozytywny");
    expect(sentimentLabel("neutral")).toContain("neutralny");
    expect(sentimentLabel("negative")).toContain("negatywny");
  });
});

describe("confidenceLabel", () => {
  it("odróżnia fakt od przybliżenia", () => {
    expect(confidenceLabel("source")).toBe("potwierdzone przez źródło");
    expect(confidenceLabel("heuristic")).toBe("dopasowanie automatyczne");
  });
});

describe("hasHeuristicMatches", () => {
  it("wykrywa choćby jedno zgadnięte powiązanie w całym feedzie", () => {
    const feed = [
      item({ assets: [{ symbol: "AAPL", match_confidence: "source" }] }),
      item({ assets: [{ symbol: "WIG20", match_confidence: "heuristic" }] }),
    ];

    expect(hasHeuristicMatches(feed)).toBe(true);
  });

  it("nie pokazuje noty o przybliżeniu, gdy wszystko potwierdziło źródło", () => {
    // Ostrzeżenie bez przedmiotu uczy ignorować ostrzeżenia.
    const feed = [item({ assets: [{ symbol: "AAPL", match_confidence: "source" }] })];

    expect(hasHeuristicMatches(feed)).toBe(false);
  });

  it("wykrywa przybliżenie także wtedy, gdy jeden news ma oba rodzaje", () => {
    // Realny przypadek: depesza pewnie powiązana z AAPL (Finnhub podał
    // symbol) i jednocześnie zgadnięta dla złota (padło słowo „złoto").
    const feed = [
      item({
        assets: [
          { symbol: "AAPL", match_confidence: "source" },
          { symbol: "XAU", match_confidence: "heuristic" },
        ],
      }),
    ];

    expect(hasHeuristicMatches(feed)).toBe(true);
  });

  it("pusty feed nie ma czego oznaczać", () => {
    expect(hasHeuristicMatches([])).toBe(false);
  });
});
