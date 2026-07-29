import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

/**
 * Vitest — testy jednostkowe frontendu (CLAUDE.md sekcja 2, tabela stacku).
 *
 * Zakres świadomie ograniczony do CZYSTYCH funkcji z `lib/` (`environment:
 * "node"`, zero jsdom, zero `@testing-library`): to, co da się sprawdzić bez
 * DOM-u i bez API — formatowanie kwot, etykiety i składanie koszyków
 * alokacji, wybór „top ruchów". Renderowanie komponentów pokrywa Playwright
 * przeciw żywemu stackowi (`e2e/`), więc druga, mockowana warstwa renderu
 * kosztowałaby utrzymanie, nie dokładając realnej pewności. Gdy pojawi się
 * komponent z logiką nie do wyciągnięcia do `lib/`, wtedy — i dopiero
 * wtedy — dokładamy jsdom.
 *
 * `vite-tsconfig-paths` daje w testach ten sam alias `@/...`, którego używa
 * Next (`tsconfig.json`), więc importy w testach wyglądają identycznie jak
 * w kodzie aplikacji.
 */
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
