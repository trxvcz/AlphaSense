/**
 * Straż po buildzie (krok 49/50): sprawdza, że service worker naprawdę powstał.
 *
 * Powód jest konkretny i kosztował jedno wdrożenie: `@serwist/next` nie
 * wspiera Turbopacka, a Next 16 buduje Turbopackiem domyślnie. Wtyczka nie
 * zgłasza wtedy błędu — po prostu nic nie emituje. Build był zielony,
 * `next build` wypisywał listę tras, a aplikacja jechała na produkcję bez
 * `sw.js`, czyli bez trybu offline, o którym mówi baner. Zielony build nie
 * może znaczyć „PWA działa", jeśli nikt nie sprawdza artefaktu.
 */
import { existsSync, statSync } from "node:fs";

const path = new URL("../public/sw.js", import.meta.url);

if (!existsSync(path) || statSync(path).size === 0) {
  console.error(
    "\nBuild nie wygenerował public/sw.js — PWA byłaby bez service workera.\n" +
      "Najczęstsza przyczyna: build poszedł Turbopackiem. `npm run build`\n" +
      "musi wołać `next build --webpack` (patrz next.config.ts).\n",
  );
  process.exit(1);
}
