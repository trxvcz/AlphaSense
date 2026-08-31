/**
 * Treść banera „dane z {data}, offline" (plan krok 49, etap 9).
 *
 * Funkcja czysta — całe formatowanie i wszystkie progi da się przetestować
 * bez przeglądarki i bez zegara systemowego (`now` wstrzykiwane).
 *
 * **Baner nie jest ozdobą, tylko oznaczeniem jakości danych** (CLAUDE.md
 * #3.15): kiedy aplikacja działa bez sieci, użytkownik patrzy na zrzut
 * sprzed jakiegoś czasu i musi to widzieć, zanim wyciągnie wniosek z liczby.
 */

/** Ile minut wstecz uznajemy jeszcze za „przed chwilą". */
const JUST_NOW_MINUTES = 2;

export type BannerInput = {
  /** Kiedy powstał wczytany zrzut cache'u (ms epoch); `null` = brak zrzutu. */
  savedAt: number | null;
  isOnline: boolean;
};

/**
 * `null` oznacza „nie pokazuj banera": jest sieć albo nie ma czego oznaczać.
 * Online świadomie milczymy — dane odświeżają się same, a stały pasek nad
 * treścią kosztowałby miejsce na ekranie 375 px.
 */
export function bannerText({ savedAt, isOnline }: BannerInput, now: number = Date.now()): string | null {
  if (isOnline) return null;
  if (savedAt === null) {
    return "Brak połączenia. Nie mamy zapisanych danych do pokazania.";
  }
  return `Brak połączenia — ${dataAgePhrase(savedAt, now)}.`;
}

/**
 * Wiek zrzutu jako gotowa fraza („dane sprzed 30 min", „dane z godz. 11:00").
 * Przyimek jest częścią frazy, a nie doklejany przez wołającego — po polsku
 * zależy od formy: „dane **sprzed** 30 min", ale „dane **z** godz. 11:00".
 *
 * Do doby podajemy godzinę, dalej datę: „dane z 14:32" niesie w portfelu inną
 * informację niż „dane z 27.08", a po dobie sama godzina wprowadzałaby w błąd.
 */
export function dataAgePhrase(savedAt: number, now: number = Date.now()): string {
  const saved = new Date(savedAt);
  const minutes = Math.floor((now - savedAt) / 60_000);

  if (minutes < JUST_NOW_MINUTES) return "dane sprzed chwili";
  if (minutes < 60) return `dane sprzed ${minutes} min`;

  const sameDay = new Date(now).toDateString() === saved.toDateString();
  const time = saved.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `dane z godz. ${time}`;

  const date = saved.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" });
  return `dane z ${date}, godz. ${time}`;
}
