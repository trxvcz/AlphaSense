/**
 * Świece OHLC (`GET /assets/{id}/candles`, krok 45).
 *
 * Indeks rynku czyta się tą samą funkcją — jest zwykłym aktywem
 * (`MarketIndex.asset_id` w `lib/analytics.ts`), więc osobna trasa
 * „świece rynku" nie jest do niczego potrzebna.
 *
 * Kwoty przychodzą jako **stringi dziesiętne** (CLAUDE.md #3.1) i takie
 * zostają w typach. Lightweight Charts przyjmuje wyłącznie `number`, więc
 * konwersja dzieje się w jednym miejscu (`toChartCandles`) i **tylko na
 * potrzeby rysowania** — nigdy do obliczeń pokazywanych użytkownikowi.
 * Wykres to piksele: utrata ostatnich cyfr znaczących jest tam niewidoczna,
 * ale ta sama konwersja w liczbie na ekranie byłaby błędem.
 */
import { apiFetch } from "@/lib/api";

/** Ten sam zamknięty zbiór co w API (`MarketIndexRangeParam`). */
export type CandleRange = "1M" | "3M" | "1Y" | "YTD" | "max";

export const CANDLE_RANGES: CandleRange[] = ["1M", "3M", "1Y", "YTD", "max"];

export type Candle = {
  /** `YYYY-MM-DD`. */
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  /** Sztuki, nie pieniądze — dlatego liczba, nie string. */
  volume: number | null;
};

export type CandleSeries = {
  symbol: string;
  name: string;
  currency: string;
  range: string;
  /** Sesje, których NIE da się pokazać (brak kompletu OHLC). */
  skipped: number;
  candles: Candle[];
};

export function getAssetCandles(assetId: string, range: CandleRange): Promise<CandleSeries> {
  return apiFetch<CandleSeries>(`/assets/${assetId}/candles?range=${range}`);
}

export type ChartCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

/** Stringi z API → liczby dla biblioteki wykresu. Patrz docstring modułu. */
export function toChartCandles(candles: Candle[]): ChartCandle[] {
  return candles.map((c) => ({
    time: c.date,
    open: Number(c.open),
    high: Number(c.high),
    low: Number(c.low),
    close: Number(c.close),
  }));
}

/**
 * Zdanie o kompletności serii — `null`, gdy nie ma czego zgłaszać.
 *
 * Dane niepełne muszą być **widocznie oznaczone** (CLAUDE.md #3.15), a
 * wykres z dziurą wygląda dokładnie tak samo jak kompletny.
 */
export function completenessNote(series: CandleSeries): string | null {
  if (series.skipped === 0) return null;
  return `Pominięto ${series.skipped} ${pluralSessions(series.skipped)} bez kompletu danych OHLC — dla tych dni dostawca podał samo zamknięcie.`;
}

/** Polska odmiana „sesja" po liczebniku: 1 sesję, 2–4 sesje, 5+ sesji. */
export function pluralSessions(count: number): string {
  const abs = Math.abs(count);
  if (abs === 1) return "sesję";
  const lastTwo = abs % 100;
  const last = abs % 10;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return "sesje";
  return "sesji";
}
