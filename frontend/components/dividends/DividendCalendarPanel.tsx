"use client";

/**
 * Kalendarz dywidend portfela (plan krok 47, etap 9) — odpowiedź na jedno
 * pytanie: „które z MOICH pozycji mają najbliżej do ex-daty i ile z tego
 * orientacyjnie wyjdzie".
 *
 * Trzy rzeczy, które ten ekran musi powiedzieć wprost, bo inaczej kłamie
 * (CLAUDE.md #3.15):
 *
 * 1. **Czego nie obejmuje.** Darmowy dostawca nie pokrywa GPW — a to rynek
 *    z największą liczbą pozycji w tym produkcie. Pusty kalendarz polskiego
 *    portfela znaczy „nie mamy danych", nie „nic Cię nie czeka". Stąd nota
 *    o pokryciu jest nad listą, a nie pod nią, i pojawia się także wtedy,
 *    gdy lista NIE jest pusta.
 * 2. **Że kwota jest szacunkiem brutto w walucie zdarzenia.** Nie w PLN
 *    (kurs właściwy dla wypłaty jest z przyszłości) i nie po podatku
 *    (rozliczenia to Etap 21, CLAUDE.md §22).
 * 3. **Że liczy się od dzisiejszej wielkości pozycji.** Dokupienie albo
 *    sprzedaż przed ex-datą zmieni wynik.
 *
 * Dostępność: bliskość ex-daty nie idzie samym kolorem — każdy wiersz ma
 * tekst („za 3 dni"), bo czerwony/zielony jako jedyny kanał informacji jest
 * wykluczony (CLAUDE.md #3.21).
 */
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/dates";
import {
  coverageNote,
  daysUntil,
  getPortfolioDividends,
  todayIso,
  type DividendEvent,
} from "@/lib/dividends";
import { decimal } from "@/lib/money";
import { getPortfolio } from "@/lib/portfolios";
import { qk } from "@/lib/queryKeys";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ListSkeleton } from "@/components/ui/ListSkeleton";

type DividendCalendarPanelProps = {
  portfolioId: string;
};

// Horyzonty do wyboru. 365 to sufit API — dalej w przyszłość żaden dostawca
// nie sięga zapowiedziami, więc szersze okno obiecywałoby dane, których nie ma.
const HORIZONS = [30, 90, 365] as const;

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function countdownLabel(days: number): string {
  if (days === 0) return "dziś";
  if (days === 1) return "jutro";
  return `za ${days} dni`;
}

function DividendRow({ event, today }: { event: DividendEvent; today: string }) {
  const days = daysUntil(event.ex_date, today);
  // Wyróżnienie „blisko" ma próg 7 dni i **kształt oraz tekst**, nie sam
  // kolor: to ostatni moment, w którym zakup jeszcze łapie się na wypłatę.
  const soon = days <= 7;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="font-medium text-zinc-900 dark:text-zinc-50">
          {event.symbol}{" "}
          <span className="text-xs font-normal text-zinc-500 dark:text-zinc-400">
            {event.market_code}
          </span>
        </span>
        <span
          className={
            soon
              ? "rounded-full border border-amber-500 px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-amber-300"
              : "text-xs text-zinc-500 dark:text-zinc-400"
          }
        >
          ex-data <time dateTime={event.ex_date}>{formatDate(event.ex_date)}</time> —{" "}
          {countdownLabel(days)}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-zinc-500 dark:text-zinc-400">Na akcję (brutto)</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">
            {decimal(event.amount_per_share)} {event.currency}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 dark:text-zinc-400">Twoja ilość</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">{decimal(event.quantity)}</dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 dark:text-zinc-400">Szacunek brutto</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">
            {decimal(event.estimated_gross)} {event.currency}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 dark:text-zinc-400">Wypłata</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">
            {/* Data wypłaty bywa jeszcze nieogłoszona — piszemy to wprost,
                zamiast zostawiać puste miejsce wyglądające na błąd. */}
            {event.pay_date ? (
              <time dateTime={event.pay_date}>{formatDate(event.pay_date)}</time>
            ) : (
              <span className="text-zinc-500 dark:text-zinc-400">jeszcze nieogłoszona</span>
            )}
          </dd>
        </div>
      </dl>

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Źródło: {event.source} · dane pobrane{" "}
        <time dateTime={event.fetched_at}>{formatDate(event.fetched_at.slice(0, 10))}</time>
      </p>
    </li>
  );
}

export function DividendCalendarPanel({ portfolioId }: DividendCalendarPanelProps) {
  const [horizonDays, setHorizonDays] = useState<number>(90);
  const today = todayIso();

  const portfolioQuery = useQuery({
    queryKey: qk.portfolio(portfolioId),
    queryFn: () => getPortfolio(portfolioId),
  });

  const calendarQuery = useQuery({
    queryKey: qk.dividends(portfolioId, horizonDays),
    queryFn: () => getPortfolioDividends(portfolioId, { horizonDays }),
  });

  const calendar = calendarQuery.data;
  const note = calendar ? coverageNote(calendar) : null;

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
              Dywidendy — {portfolioQuery.data.name}
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

      <fieldset className="flex flex-wrap items-center gap-2">
        <legend className="sr-only">Horyzont kalendarza</legend>
        {HORIZONS.map((days) => (
          <button
            key={days}
            type="button"
            aria-pressed={horizonDays === days}
            onClick={() => setHorizonDays(days)}
            className={
              horizonDays === days
                ? "rounded-full bg-zinc-900 px-3 py-1 text-sm text-zinc-50 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:bg-zinc-100 dark:text-zinc-900"
                : "rounded-full border border-zinc-300 px-3 py-1 text-sm text-zinc-700 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700 dark:text-zinc-300"
            }
          >
            {days === 365 ? "rok" : `${days} dni`}
          </button>
        ))}
      </fieldset>

      {/* Nota o pokryciu NAD listą i niezależnie od tego, czy lista jest
          pusta: dziura w danych dotyczy także portfela, który coś pokazuje. */}
      {note && (
        <p className="rounded-lg border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-600 dark:bg-transparent dark:text-amber-200">
          {note}
        </p>
      )}

      {calendarQuery.isLoading && <ListSkeleton rows={4} />}

      {calendarQuery.isError && (
        <ErrorState
          message={apiErrorMessage(calendarQuery.error, "Nie udało się pobrać kalendarza dywidend.")}
          onRetry={() => void calendarQuery.refetch()}
        />
      )}

      {calendar && calendar.items.length === 0 && (
        <EmptyState
          title="Brak nadchodzących dywidend"
          description={
            calendar.assets_covered === 0
              ? "Żadnej z Twoich pozycji nie obejmuje dziś nasze źródło danych o dywidendach — patrz uwaga powyżej."
              : `W ciągu najbliższych ${calendar.horizon_days} dni żadna z objętych danymi pozycji nie ma zapowiedzianej ex-daty. Spróbuj szerszego horyzontu.`
          }
        />
      )}

      {calendar && calendar.items.length > 0 && (
        <>
          <ul className="flex flex-col gap-3">
            {calendar.items.map((event) => (
              <DividendRow key={`${event.symbol}-${event.ex_date}`} event={event} today={today} />
            ))}
          </ul>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Kwoty są <strong>brutto</strong>, w walucie notowania i <strong>przed podatkiem</strong>
            . Szacunek liczymy z dzisiejszej wielkości pozycji — jeśli dokupisz lub sprzedasz przed
            ex-datą, wypłata będzie inna. To nie jest rozliczenie podatkowe.
          </p>
        </>
      )}
    </section>
  );
}
