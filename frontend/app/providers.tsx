"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

/**
 * Jedna instancja QueryClient na drzewo komponentów klienckich
 * (React 19 + App Router: `useState`, nie moduł-singleton, żeby nie
 * przeciekał między requestami na serwerze).
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Dane są z EOD — nie ma sensu odpytywać agresywnie.
            staleTime: 60 * 1000,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
