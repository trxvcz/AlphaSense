import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Build produkcyjny pakuje serwer i realnie używane zależności do
   * `.next/standalone` (uruchamiane przez `node server.js`, patrz
   * `frontend/Dockerfile`, stopień `prod`). Bez tego obraz produkcyjny
   * musiałby nieść całe `node_modules` i źródła.
   *
   * Nie wpływa na `npm run dev` ani na `make check` — `next build` po prostu
   * dokłada katalog `.next/standalone`.
   */
  output: "standalone",
};

export default nextConfig;
