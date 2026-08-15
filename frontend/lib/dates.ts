/**
 * Formatowanie dat `YYYY-MM-DD` przychodzących z API (np. `as_of`,
 * `valuations[].date`) — jedno miejsce, `pl-PL`.
 */
const dateFormatter = new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium" });

export function formatDate(isoDate: string): string {
  return dateFormatter.format(new Date(`${isoDate}T00:00:00`));
}

/**
 * Pełny moment (`published_at` newsów, krok 46) — data i godzina.
 *
 * Osobna funkcja, bo wejście jest inne: `formatDate` dostaje `YYYY-MM-DD`
 * i sam dokleja północ, tutaj przychodzi ISO 8601 z offsetem i doklejanie
 * czegokolwiek zepsułoby parsowanie. Godzina jest częścią informacji —
 * przy feedzie odświeżanym co pół godziny „11 sierpnia" nie odróżnia
 * depeszy sprzed chwili od porannej.
 */
const dateTimeFormatter = new Intl.DateTimeFormat("pl-PL", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDateTime(isoDateTime: string): string {
  return dateTimeFormatter.format(new Date(isoDateTime));
}
