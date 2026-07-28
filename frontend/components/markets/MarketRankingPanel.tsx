"use client";

/**
 * Panel „Twoje rynki" (plan krok 34, ADR-102) — rynki, na których użytkownik
 * jest realnie zainwestowany, posortowane malejąco po wadze w wartości
 * wycenionego portfela, każdy z indeksem referencyjnym swojego rynku.
 *
 * To jest odpowiedź na pytanie „gdzie właściwie stoją moje pieniądze i co się
 * tam dzieje" — dlatego rynek bez indeksu NIE znika z listy i nie dostaje
 * pustego wykresu, tylko pokazuje samą wagę z wyjaśnieniem (skill
 * `analityka-struktury`). Kolejność bierzemy z backendu i nie sortujemy
 * ponownie — waga jest tam kwantyzowana tak, żeby sumowała się do 1.
 *
 * Client Component: hooki TanStack Query żyją tutaj, `page.tsx` zostaje
 * Server Component i tylko rozpakowuje `params` (wzorzec z kroków 32 i 33).
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { getMarketRanking, type MarketRankingItem } from "@/lib/analytics";
import { getPortfolio } from "@/lib/portfolios";
import { qk } from "@/lib/queryKeys";
import { decimal, pct } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { changeColorClass } from "@/lib/changeColor";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ListSkeleton } from "@/components/ui/ListSkeleton";
import { MarketSparkline } from "@/components/charts/MarketSparkline";

type MarketRankingPanelProps = {
  portfolioId: string;
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/**
 * Jeden rynek. Wszystkie liczby, które niesie sparkline, są obok jako tekst
 * (wartość indeksu, zmiana d/d, data notowania) — to jest tekstowa
 * alternatywa dla kanwy ECharts, której czytnik ekranu nie odczyta. Tabela z
 * trzydziestoma notowaniami na rynek byłaby w tym miejscu szumem, nie pomocą.
 */
function MarketRow({ item }: { item: MarketRankingItem }) {
  const weightPercent = `${Math.min(100, Number(item.weight) * 100)}%`;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="font-medium text-zinc-900 dark:text-zinc-50">{item.market_code}</span>
          <span className="truncate text-sm text-zinc-600 dark:text-zinc-400">
            {item.market_name}
          </span>
        </div>
        <span className="shrink-0 text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
          {pct(item.weight)}
        </span>
      </div>

      {/* Pasek wagi — czysty CSS, nie wykres: jedna wartość na wiersz nie
          potrzebuje kanwy, a na 375 px każdy piksel wysokości się liczy. */}
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800"
        role="presentation"
      >
        <div className="h-full rounded-full bg-blue-600" style={{ width: weightPercent }} />
      </div>

      {item.index ? (
        <div className="flex items-center gap-3">
          <div className="flex min-w-0 flex-col">
            <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
              {item.index.symbol}
            </span>
            <span className="tabular-nums text-zinc-900 dark:text-zinc-50">
              {decimal(item.index.value)}
            </span>
            {item.index.change_1d ? (
              <span
                className={`text-sm tabular-nums ${changeColorClass(item.index.change_1d.pct)}`}
              >
                {pct(item.index.change_1d.pct)} ({decimal(item.index.change_1d.abs)})
              </span>
            ) : (
              <span className="text-sm text-zinc-500 dark:text-zinc-400">
                brak zmiany d/d (jedno notowanie)
              </span>
            )}
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              dane z {formatDate(item.index.as_of)}
            </span>
          </div>
          <div className="min-w-0 flex-1">
            <MarketSparkline series={item.index.series_30d} symbol={item.index.symbol} />
          </div>
        </div>
      ) : (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Ten rynek nie ma jeszcze indeksu referencyjnego z notowaniami — pokazujemy samą wagę.
        </p>
      )}
    </li>
  );
}

export function MarketRankingPanel({ portfolioId }: MarketRankingPanelProps) {
  const portfolioQuery = useQuery({
    queryKey: qk.portfolio(portfolioId),
    queryFn: () => getPortfolio(portfolioId),
  });

  const marketsQuery = useQuery({
    queryKey: qk.markets(portfolioId),
    queryFn: () => getMarketRanking(portfolioId),
  });

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
              Twoje rynki — {portfolioQuery.data.name}
            </h1>
            <Link
              href={`/portfolios/${portfolioId}`}
              className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
            >
              ← Wróć do dashboardu portfela
            </Link>
          </>
        )}
        {portfolioQuery.isError && (
          <ErrorState
            message={apiErrorMessage(portfolioQuery.error, "Nie udało się wczytać portfela.")}
            onRetry={() => void portfolioQuery.refetch()}
          />
        )}
      </div>

      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Rynki, na których faktycznie masz pozycje, uszeregowane wg udziału w wartości portfela.
        Obok — indeks referencyjny każdego z nich, żeby było widać, w jakim otoczeniu pracują
        Twoje pieniądze.
      </p>

      {marketsQuery.isLoading && <ListSkeleton rows={3} />}

      {marketsQuery.isError && (
        <ErrorState
          message={apiErrorMessage(marketsQuery.error, "Nie udało się wczytać rankingu rynków.")}
          onRetry={() => void marketsQuery.refetch()}
        />
      )}

      {marketsQuery.isSuccess && marketsQuery.data.length === 0 && (
        <EmptyState
          title="Nie jesteś jeszcze zainwestowany na żadnym rynku"
          description="Ranking pojawi się, gdy portfel będzie miał przynajmniej jedną pozycję z aktualną wyceną."
          action={
            <Link
              href={`/portfolios/${portfolioId}`}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600"
            >
              Dodaj pozycję
            </Link>
          }
        />
      )}

      {marketsQuery.isSuccess && marketsQuery.data.length > 0 && (
        <>
          <ul aria-label="Rynki wg udziału w portfelu" className="flex flex-col gap-3">
            {marketsQuery.data.map((item) => (
              <MarketRow key={item.market_code} item={item} />
            ))}
          </ul>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Wagi liczone tylko z pozycji, które udało się wycenić — pozycja bez aktualnej ceny nie
            jest liczona jako zero, tylko wykluczana z mianownika.
          </p>
        </>
      )}
    </section>
  );
}
