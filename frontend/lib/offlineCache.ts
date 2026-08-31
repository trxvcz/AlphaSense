/**
 * Trwały cache zapytań w IndexedDB (plan krok 49, etap 9) — to on sprawia,
 * że aplikacja dodana do ekranu głównego **otwiera się bez sieci**.
 *
 * ## Dlaczego to jest kod wrażliwy na izolację danych
 *
 * `lib/queryKeys.ts` nie ma segmentu użytkownika, a `AuthProvider` czyści
 * cache przy każdej zmianie sesji właśnie dlatego (CLAUDE.md #3.2/#3.10).
 * Zapis tego samego cache'u na dysk znosiłby tamto zabezpieczenie: dane
 * użytkownika A przeżyłyby wylogowanie i mogłyby zostać wczytane w sesji B
 * na tym samym urządzeniu.
 *
 * Stąd trzy reguły, których nie wolno tu poluzować:
 *
 * 1. **Wpis jest przypisany do właściciela** — klucz zawiera `sub` z tokenu
 *    (identyfikator użytkownika). Wczytujemy wyłącznie wpis, którego
 *    właściciel zgadza się z bieżącą sesją.
 * 2. **Wylogowanie kasuje wszystko** (`clearPersistedCache`), nie tylko wpis
 *    bieżącego użytkownika.
 * 3. **Sam token nigdy nie trafia na dysk.** Czytamy z niego tylko `sub`;
 *    access token zostaje wyłącznie w pamięci (`lib/auth/tokenStore.ts`).
 *
 * Payload JWT dekodujemy **bez weryfikacji podpisu** — po stronie
 * przeglądarki nie ma czym go zweryfikować i nie o to chodzi. To jest
 * wyłącznie etykieta „czyj jest ten cache", a nie dowód tożsamości;
 * autoryzacja dzieje się w całości na backendzie.
 */
import { del, get, set } from "idb-keyval";
import type { DehydratedState } from "@tanstack/react-query";

const STORE_KEY = "alphasense-query-cache";

/** Starszy zrzut nie jest wczytywany — lepiej pusty ekran niż tydzień temu. */
export const MAX_CACHE_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export type PersistedCache = {
  /** `sub` z access tokenu — patrz reguła 1 w docstringu modułu. */
  owner: string;
  /** Kiedy zrzut powstał (ms epoch) — źródło daty w banerze „dane z…". */
  savedAt: number;
  state: DehydratedState;
};

/**
 * Wyciąga `sub` z access tokenu. `null`, gdy tokenu nie ma albo nie da się
 * go rozebrać — wtedy po prostu nie zapisujemy i nie wczytujemy niczego.
 */
export function cacheOwner(accessToken: string | null): string | null {
  if (accessToken === null) return null;
  const payload = accessToken.split(".")[1];
  if (payload === undefined) return null;
  try {
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const parsed: unknown = JSON.parse(json);
    if (typeof parsed !== "object" || parsed === null) return null;
    const sub = (parsed as { sub?: unknown }).sub;
    return typeof sub === "string" && sub !== "" ? sub : null;
  } catch {
    return null;
  }
}

export async function savePersistedCache(cache: PersistedCache): Promise<void> {
  try {
    await set(STORE_KEY, cache);
  } catch {
    // IndexedDB bywa niedostępny (tryb prywatny Firefoksa, brak miejsca).
    // Brak trwałego cache'u degraduje aplikację do trybu online — to jest
    // gorsze doświadczenie, ale nie błąd, więc nie zawracamy tym użytkownika.
  }
}

/**
 * Wczytuje zrzut, ale **tylko** jeśli należy do bieżącej sesji i nie jest
 * przeterminowany. W każdym innym wypadku `null` — i to jest właściwa
 * odpowiedź także wtedy, gdy wpis istnieje, ale jest cudzy.
 */
export async function loadPersistedCache(
  owner: string | null,
  now: number = Date.now(),
): Promise<PersistedCache | null> {
  if (owner === null) return null;
  try {
    const stored = await get<PersistedCache>(STORE_KEY);
    if (stored === undefined) return null;
    if (stored.owner !== owner) return null;
    if (now - stored.savedAt > MAX_CACHE_AGE_MS) return null;
    return stored;
  } catch {
    return null;
  }
}

/** Wywoływane przy wylogowaniu — kasuje zrzut niezależnie od właściciela. */
export async function clearPersistedCache(): Promise<void> {
  try {
    await del(STORE_KEY);
  } catch {
    // jak w `savePersistedCache`
  }
}
