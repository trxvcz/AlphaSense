"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import { OfflineCacheProvider } from "@/lib/offline/OfflineCacheProvider";

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
    <QueryClientProvider client={queryClient}>
      {/* `OfflineCacheProvider` wewnątrz `AuthProvider`: trwałość cache'u
          zależy od sesji (zrzut jest przypisany do użytkownika i kasowany
          przy wylogowaniu — patrz `lib/offlineCache.ts`). */}
      <AuthProvider>
        <OfflineCacheProvider>{children}</OfflineCacheProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
