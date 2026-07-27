/**
 * Formatowanie dat `YYYY-MM-DD` przychodzących z API (np. `as_of`,
 * `valuations[].date`) — jedno miejsce, `pl-PL`.
 */
const dateFormatter = new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium" });

export function formatDate(isoDate: string): string {
  return dateFormatter.format(new Date(`${isoDate}T00:00:00`));
}
