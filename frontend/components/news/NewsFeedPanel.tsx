"use client";

/**
 * Feed newsów portfela (plan krok 46, etap 9) — odpowiedź na pytanie „co się
 * dzieje z MOIMI pozycjami", a nie kolejny agregator wiadomości gospodarczych
 * (CLAUDE.md §1). Stąd brak trybu „wszystkie newsy": każdy wpis jest tu
 * dlatego, że dotyczy czegoś, co użytkownik trzyma.
 *
 * Trzy rzeczy, które ten widok musi pokazać, bo inaczej kłamie
 * (CLAUDE.md #3.15 — dane przybliżone i niepełne muszą być oznaczane):
 *
 * 1. **Skąd wzięło się powiązanie z aktywem.** `source` (dostawca pytany
 *    o symbol) to fakt, `heuristic` (nasze dopasowanie polskiego tekstu)
 *    to przybliżenie, które bywa mylne. Oznaczenie jest per aktywo, bo
 *    jedna depesza potrafi być pewnie powiązana z AAPL i zgadnięta dla złota.
 * 2. **Brak oceny sentymentu.** Polskie feedy RSS go nie publikują, a Alpha
 *    Vantage pokrywa w praktyce wyłącznie spółki amerykańskie. Brak oceny
 *    to stan normalny, nie ładowanie i nie błąd — więc jest napisany
 *    wprost, zamiast być pustym miejscem.
 * 3. **Pozycje, o których nic nie ma.** Użytkownik z pozycją bez newsów
 *    i użytkownik, którego pozycji nie umiemy rozpoznać w tekście, widzą
 *    ten sam pusty feed. `assets_without_news` pozwala powiedzieć, czego
 *    ten ekran NIE obejmuje.
 *
 * Dostępność: wydźwięk sentymentu nigdy nie idzie samym kolorem — każdy
 * znacznik ma tekst („wydźwięk pozytywny"), bo czerwony/zielony jako jedyny
 * kanał informacji jest wykluczony (CLAUDE.md #3.21).
 *
 * Client Component: hooki TanStack Query i stan filtra żyją tutaj,
 * `page.tsx` zostaje Server Component i tylko rozpakowuje `params`
 * (wzorzec z kroków 32-34).
 */
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import {
  confidenceLabel,
  getPortfolioNews,
  hasHeuristicMatches,
  isSafeHttpUrl,
  sentimentLabel,
  sentimentTone,
  type NewsAssetRef,
  type NewsItem,
} from "@/lib/news";
import { getPortfolio } from "@/lib/portfolios";
import { qk } from "@/lib/queryKeys";
import { formatDateTime } from "@/lib/dates";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ListSkeleton } from "@/components/ui/ListSkeleton";

type NewsFeedPanelProps = {
  portfolioId: string;
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/**
 * Znacznik aktywa. Powiązanie zgadnięte przez nas dostaje obwódkę
 * przerywaną i znak zapytania — kształt, nie tylko kolor, żeby różnica
 * była czytelna także w skali szarości i dla daltonistów.
 *
 * Opis pewności idzie **wyłącznie** przez `sr-only`, bez `title` na tym
 * samym elemencie: `title` i tekst dla czytnika ekranu dublowałyby się
 * w odczycie. Widzący dostaje kształt, niewidzący — zdanie.
 */
function AssetChip({ asset }: { asset: NewsAssetRef }) {
  const guessed = asset.match_confidence === "heuristic";
  return (
    <span
      className={
        guessed
          ? "inline-flex items-center gap-1 rounded-full border border-dashed border-amber-500 px-2 py-0.5 text-xs font-medium text-amber-800 dark:border-amber-500 dark:text-amber-300"
          : "inline-flex items-center gap-1 rounded-full border border-zinc-300 bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-800 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
      }
    >
      {asset.symbol}
      {guessed && <span aria-hidden="true">?</span>}
      <span className="sr-only"> — {confidenceLabel(asset.match_confidence)}</span>
    </span>
  );
}

function SentimentBadge({ item }: { item: NewsItem }) {
  if (item.sentiment === null) {
    // Napisane wprost, nie pominięte: brak oceny to informacja, a puste
    // miejsce wygląda jak coś, co się jeszcze doczytuje.
    return (
      <span className="text-xs text-zinc-500 dark:text-zinc-400">brak oceny wydźwięku</span>
    );
  }
  const tone = sentimentTone(item.sentiment);
  const toneClass =
    tone === "positive"
      ? "text-emerald-700 dark:text-emerald-400"
      : tone === "negative"
        ? "text-red-700 dark:text-red-400"
        : "text-zinc-600 dark:text-zinc-400";
  const sign = tone === "positive" ? "▲" : tone === "negative" ? "▼" : "■";
  return (
    <span className={`text-xs font-medium ${toneClass}`}>
      {/* Znak i słowo obok siebie — kolor jest tu wzmocnieniem, nie nośnikiem. */}
      <span aria-hidden="true">{sign} </span>
      {sentimentLabel(tone)}
      {item.sentiment_source && (
        <span className="font-normal text-zinc-500 dark:text-zinc-400">
          {" "}
          wg {item.sentiment_source}
        </span>
      )}
    </span>
  );
}

function NewsRow({ item }: { item: NewsItem }) {
  // Tytuł bez linku, gdy adres nie jest zwykłym http(s) — treść newsa
  // zostaje widoczna, znika tylko kliknięcie prowadzące nie wiadomo gdzie.
  // Ukrycie całego wpisu byłoby gorsze: użytkownik nie wiedziałby, że
  // coś zniknęło, a to jest sytuacja, o której ma się dowiedzieć.
  const linkable = isSafeHttpUrl(item.url);

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      {linkable ? (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-zinc-900 underline-offset-2 outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-50"
        >
          {item.title}
        </a>
      ) : (
        <p className="font-medium text-zinc-900 dark:text-zinc-50">
          {item.title}{" "}
          <span className="text-xs font-normal text-zinc-500 dark:text-zinc-400">
            (odnośnik pominięty — źródło podało niepoprawny adres)
          </span>
        </p>
      )}

      {item.summary && (
        <p className="line-clamp-3 text-sm text-zinc-600 dark:text-zinc-400">{item.summary}</p>
      )}

      {item.assets.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {item.assets.map((asset) => (
            <li key={asset.symbol}>
              <AssetChip asset={asset} />
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-xs text-zinc-500 dark:text-zinc-400">
          {item.source} · <time dateTime={item.published_at}>{formatDateTime(item.published_at)}</time>
        </span>
        <SentimentBadge item={item} />
      </div>
    </li>
  );
}

export function NewsFeedPanel({ portfolioId }: NewsFeedPanelProps) {
  const [withSentimentOnly, setWithSentimentOnly] = useState(false);

  const portfolioQuery = useQuery({
    queryKey: qk.portfolio(portfolioId),
    queryFn: () => getPortfolio(portfolioId),
  });

  const newsQuery = useQuery({
    queryKey: qk.news(portfolioId, withSentimentOnly),
    queryFn: () => getPortfolioNews(portfolioId, { withSentimentOnly }),
  });

  const feed = newsQuery.data;

  return (
    <section className="flex flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-1">
        {portfolioQuery.isLoading && (
          <div
            role="status"
            aria-label="Ładowanie"
            className="h-8 w-56 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800"
          />
        )}
        {portfolioQuery.isSuccess && (
          <>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Newsy — {portfolioQuery.data.name}
            </h1>
            <Link
              href={`/portfolios/${portfolioId}`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              ← Wróć do dashboardu portfela
            </Link>
          </>
        )}
      </div>

      <label className="flex w-fit items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
        <input
          type="checkbox"
          checked={withSentimentOnly}
          onChange={(event) => setWithSentimentOnly(event.target.checked)}
          className="size-4 rounded border-zinc-300 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700"
        />
        {/* Filtr po OBECNOŚCI oceny, nie po jej wartości — „tylko pozytywne"
            przy dzisiejszym pokryciu sentymentu (praktycznie zero dla GPW)
            byłoby obietnicą pustego ekranu. */}
        Pokaż tylko newsy z oceną wydźwięku
      </label>

      {newsQuery.isLoading && <ListSkeleton rows={5} />}

      {newsQuery.isError && (
        <ErrorState
          message={apiErrorMessage(newsQuery.error, "Nie udało się pobrać newsów.")}
          onRetry={() => void newsQuery.refetch()}
        />
      )}

      {feed && feed.items.length === 0 && (
        <EmptyState
          title={
            withSentimentOnly
              ? "Żaden news o Twoich pozycjach nie ma oceny wydźwięku"
              : "Brak newsów o Twoich pozycjach"
          }
          description={
            withSentimentOnly
              ? "Ocenę wydźwięku publikuje dziś wyłącznie dostawca danych zagranicznych — polskie serwisy jej nie podają. Odznacz filtr, żeby zobaczyć pozostałe newsy."
              : "Newsy zbieramy z polskich serwisów gospodarczych i od dostawców danych. Jeśli portfel jest nowy, pierwsze wpisy pojawią się w ciągu najbliższej godziny."
          }
        />
      )}

      {feed && feed.items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {feed.items.map((item) => (
            <NewsRow key={item.id} item={item} />
          ))}
        </ul>
      )}

      {feed && hasHeuristicMatches(feed.items) && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Znaczniki z przerywaną obwódką i znakiem &bdquo;?&rdquo; oznaczają powiązanie dopasowane
          automatycznie po treści — może być nietrafne. Pozostałe potwierdził dostawca danych.
        </p>
      )}

      {feed && feed.assets_without_news.length > 0 && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Ten feed nie obejmuje pozycji: {feed.assets_without_news.join(", ")} — nie mamy dla nich
          żadnego newsu.
        </p>
      )}
    </section>
  );
}
