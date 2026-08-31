"use client";

/**
 * Trwałość cache'u zapytań i stan „jesteśmy offline" (plan krok 49, etap 9).
 *
 * Provider robi trzy rzeczy:
 *
 * 1. po zalogowaniu wczytuje z IndexedDB zrzut należący **do tej sesji**
 *    i wstrzykuje go do TanStack Query (`hydrate`),
 * 2. zapisuje zrzut z dławieniem, gdy cache się zmienia,
 * 3. kasuje zapis przy wylogowaniu.
 *
 * Reguły izolacji danych i powód, dla którego zrzut jest przypisany do
 * właściciela, opisuje `lib/offlineCache.ts` — to tam jest sedno, tu jest
 * tylko podpięcie do cyklu życia Reacta.
 *
 * **Hydratacja jest jednorazowa na sesję** i nie nadpisuje danych świeższych:
 * `hydrate` z TanStack Query wstawia wpis tylko wtedy, gdy w pamięci nie ma
 * nowszego. Dzięki temu wczytanie zrzutu nie cofa ekranu, na który zdążyły
 * już wpaść świeże dane z API.
 */
import { hydrate, dehydrate, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";
import { getAccessToken, subscribeAccessToken } from "@/lib/auth/tokenStore";
import {
  cacheOwner,
  clearPersistedCache,
  loadPersistedCache,
  savePersistedCache,
} from "@/lib/offlineCache";

/** Jak często najwyżej zapisujemy zrzut — zapis idzie do IndexedDB, a cache
 * potrafi zmieniać się kilkanaście razy na sekundę przy wejściu na dashboard. */
const SAVE_THROTTLE_MS = 5_000;

type OfflineCacheValue = {
  /** Kiedy powstał zrzut, z którego korzysta ekran; `null` = brak zrzutu. */
  savedAt: number | null;
  isOnline: boolean;
};

const OfflineCacheContext = createContext<OfflineCacheValue>({
  savedAt: null,
  isOnline: true,
});

export function useOfflineCache(): OfflineCacheValue {
  return useContext(OfflineCacheContext);
}

function subscribeOnline(callback: () => void): () => void {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

export function OfflineCacheProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const accessToken = useSyncExternalStore(
    subscribeAccessToken,
    getAccessToken,
    // SSR nie zna tokenu (żyje w pamięci przeglądarki) — patrz `AuthProvider`.
    () => null,
  );
  const isOnline = useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    // Na serwerze zakładamy „online": baner offline ma się pojawić dopiero
    // wtedy, gdy przeglądarka realnie zgłosi brak sieci, a nie mignąć w SSR.
    () => true,
  );

  // Znacznik zrzutu trzymamy **razem z właścicielem**, a nie jako gołą liczbę:
  // dzięki temu wylogowanie zeruje go przez wyliczenie (`savedAt` niżej), a nie
  // przez `setState` w ciele efektu, które wymuszałoby kaskadowy render.
  const [saved, setSaved] = useState<{ owner: string; at: number } | null>(null);
  const owner = cacheOwner(accessToken);
  const savedAt = saved !== null && saved.owner === owner ? saved.at : null;
  const hydratedFor = useRef<string | null>(null);

  useEffect(() => {
    if (owner === null) {
      // Wylogowanie (albo wygaśnięcie sesji): `AuthProvider` czyści cache w
      // pamięci, my kasujemy jego odpowiednik na dysku. Bez tego dane
      // zostałyby na urządzeniu po wylogowaniu.
      hydratedFor.current = null;
      void clearPersistedCache();
      return;
    }
    if (hydratedFor.current === owner) return;
    hydratedFor.current = owner;

    let cancelled = false;
    void loadPersistedCache(owner).then((stored) => {
      if (cancelled || stored === null) return;
      hydrate(queryClient, stored.state);
      setSaved({ owner, at: stored.savedAt });
    });
    return () => {
      cancelled = true;
    };
  }, [owner, queryClient]);

  useEffect(() => {
    if (owner === null) return;

    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = queryClient.getQueryCache().subscribe(() => {
      if (timer !== null) return;
      timer = setTimeout(() => {
        timer = null;
        const now = Date.now();
        void savePersistedCache({ owner, savedAt: now, state: dehydrate(queryClient) });
        setSaved({ owner, at: now });
      }, SAVE_THROTTLE_MS);
    });

    return () => {
      if (timer !== null) clearTimeout(timer);
      unsubscribe();
    };
  }, [owner, queryClient]);

  return (
    <OfflineCacheContext.Provider value={{ savedAt, isOnline }}>
      {children}
    </OfflineCacheContext.Provider>
  );
}
