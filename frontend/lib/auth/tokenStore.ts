/**
 * Access token trzymany WYŁĄCZNIE w pamięci procesu (moduł, nie
 * localStorage/sessionStorage) — patrz CLAUDE.md, decyzja architektoniczna
 * „access token żyje wyłącznie in-memory" (bezpieczeństwo XSS).
 *
 * To jest zwykły moduł (nie React Context), bo `lib/api.ts` musi umieć
 * odczytać/wyczyścić token spoza drzewa komponentów (np. w trakcie
 * silent-refresh przy 401). `lib/auth/AuthProvider.tsx` subskrybuje ten
 * moduł przez `useSyncExternalStore`, żeby komponenty (nawigacja, guard)
 * mogły się na niego reaktywnie przerenderować.
 */

type Listener = () => void;

let accessToken: string | null = null;
const listeners = new Set<Listener>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  if (token === accessToken) return;
  accessToken = token;
  for (const listener of listeners) listener();
}

export function subscribeAccessToken(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
