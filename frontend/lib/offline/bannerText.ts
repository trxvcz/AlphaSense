/**
 * Treść banera „dane z {data}, offline" (plan krok 49, etap 9; przeniesione
 * do katalogu komunikatów w kroku 50).
 *
 * Funkcja czysta — całe formatowanie i wszystkie progi da się przetestować
 * bez przeglądarki i bez zegara systemowego (`now` wstrzykiwane).
 *
 * **Zwraca klucz komunikatu i jego parametry, a nie gotowe zdanie.** Dzięki
 * temu logika („co pokazać") zostaje tutaj i jest testowalna, a treść
 * („jakimi słowami") mieszka w `messages/pl.json` — patrz `lib/i18n.ts`.
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

/** Klucz w przestrzeni `offline.banner` razem z parametrami do podstawienia. */
export type Message = {
  key: string;
  values?: Record<string, string | number>;
};

/** Baner albo mówi „nie mam nic", albo pokazuje wiek zrzutu — a wiek jest
 * osobnym komunikatem, bo to on decyduje o odmianie („sprzed" vs „z"). */
export type BannerMessage = { key: "noData" } | { key: "withAge"; age: Message };

/**
 * `null` oznacza „nie pokazuj banera": jest sieć albo nie ma czego oznaczać.
 * Online świadomie milczymy — dane odświeżają się same, a stały pasek nad
 * treścią kosztowałby miejsce na ekranie 375 px.
 */
export function bannerMessage(
  { savedAt, isOnline }: BannerInput,
  now: number = Date.now(),
): BannerMessage | null {
  if (isOnline) return null;
  if (savedAt === null) return { key: "noData" };
  return { key: "withAge", age: dataAgeMessage(savedAt, now) };
}

/**
 * Wiek zrzutu jako klucz + parametry („dane sprzed 30 min", „dane z godz.
 * 11:00"). Przyimek jest częścią komunikatu, a nie doklejany przez
 * wołającego — po polsku zależy od formy: „dane **sprzed** 30 min", ale
 * „dane **z** godz. 11:00".
 *
 * Do doby podajemy godzinę, dalej datę: „dane z 14:32" niesie w portfelu inną
 * informację niż „dane z 27.08", a po dobie sama godzina wprowadzałaby w błąd.
 */
export function dataAgeMessage(savedAt: number, now: number = Date.now()): Message {
  const saved = new Date(savedAt);
  const minutes = Math.floor((now - savedAt) / 60_000);

  if (minutes < JUST_NOW_MINUTES) return { key: "ageJustNow" };
  if (minutes < 60) return { key: "ageMinutes", values: { minutes } };

  const time = saved.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  const sameDay = new Date(now).toDateString() === saved.toDateString();
  if (sameDay) return { key: "ageToday", values: { time } };

  const date = saved.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" });
  return { key: "ageOlder", values: { date, time } };
}
