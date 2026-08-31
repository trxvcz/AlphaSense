/**
 * Strona zastępcza dla nawigacji bez sieci (plan krok 49, etap 9).
 *
 * Trafiają tu **wyłącznie trasy, których użytkownik jeszcze nie odwiedził**
 * — odwiedzone otwierają się normalnie, z danymi ze zrzutu w IndexedDB
 * (`lib/offlineCache.ts`), z banerem oznaczającym ich wiek. Ta strona
 * istnieje po to, żeby zamiast komunikatu przeglądarki („nie można otworzyć
 * strony") pokazać coś, co tłumaczy sytuację i prowadzi z powrotem.
 *
 * Statyczna i bez zależności od API — musi działać, gdy nie działa nic innego.
 */
import Link from "next/link";

export const metadata = {
  title: "Brak połączenia — AlphaSense",
};

export default function OfflinePage() {
  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 py-16 text-center">
      <h1 className="text-xl font-semibold">Brak połączenia</h1>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Tej części aplikacji nie mamy zapisanej na urządzeniu, więc nie da się jej otworzyć
        bez sieci. Ekrany odwiedzone wcześniej działają dalej — z danymi z ostatniego
        pobrania, wyraźnie oznaczonymi datą.
      </p>
      <div>
        <Link
          href="/dashboard"
          className="inline-block rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600"
        >
          Wróć do pulpitu
        </Link>
      </div>
    </div>
  );
}
