/**
 * Service worker (plan krok 49, etap 9) — budowany przez Serwist z tego
 * źródła do `public/sw.js` (`next.config.ts`).
 *
 * **Dlaczego `skipWaiting` + `clientsClaim`, a nie „czekaj na zamknięcie
 * kart":** największe ryzyko zapisane w planie etapu 9 to service worker,
 * który zablokuje użytkownikom aktualizację aplikacji. Domyślne zachowanie
 * SW (nowa wersja czeka, aż wszystkie karty zostaną zamknięte) na PWA
 * dodanej do ekranu głównego oznacza w praktyce „nigdy" — telefon trzyma tę
 * kartę tygodniami. Natychmiastowe przejęcie kontroli jest tu bezpieczniejsze
 * niż teoretycznie czystsze wersjonowanie: aplikacja czyta świeże dane z API,
 * a nie trzyma stanu w SW.
 *
 * **Ścieżka wyjścia z zepsutego SW** (druga połowa tego samego ryzyka):
 * `precacheEntries` obejmuje wyłącznie zasoby zbudowane przez Next z
 * bieżącego wydania, a `navigationPreload` sprawia, że nawigacja rusza
 * równolegle do startu workera. Gdyby mimo to trzeba było „odkleić"
 * użytkownika od starej wersji, wystarczy wydać build z
 * `disable: true` w `next.config.ts` — Serwist wygeneruje wtedy SW, który
 * sam się wyrejestrowuje i czyści cache.
 */
import { defaultCache } from "@serwist/next/worker";
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { Serwist } from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: defaultCache,
  fallbacks: {
    entries: [
      {
        // Nawigacja bez sieci ląduje na `/offline`, a nie na stronie błędu
        // przeglądarki. Sam dashboard offline pokazuje ostatnie dane z
        // IndexedDB (patrz `app/providers.tsx`) — ten fallback jest dla
        // tras, których użytkownik jeszcze nie odwiedził.
        url: "/offline",
        matcher: ({ request }) => request.destination === "document",
      },
    ],
  },
});

serwist.addEventListeners();
