"use client";

/**
 * Kontekst sesji użytkownika. Access token żyje w `lib/auth/tokenStore.ts`
 * (moduł, nie React state) — ten provider tylko:
 *
 * 1. subskrybuje token (`useSyncExternalStore`), żeby konsumenci
 *    (nawigacja, guard tras) przerenderowali się na zmianę,
 * 2. przy montażu robi cichy `POST /auth/refresh`, żeby odzyskać sesję po
 *    odświeżeniu strony (F5) — nieudany refresh = „niezalogowany", bez
 *    błędu w konsoli/UI (decyzja architektoniczna, CLAUDE.md),
 * 3. wystawia `login`/`logout` do formularzy i nawigacji,
 * 4. czyści cache TanStack Query przy każdej zmianie sesji (patrz niżej).
 *
 * Punkt 4 jest wymogiem izolacji danych (CLAUDE.md #3.2/#3.10), nie
 * optymalizacją: klucze w `lib/queryKeys.ts` nie zawierają segmentu
 * użytkownika, a `staleTime` wynosi 60 s (`app/providers.tsx`). Bez
 * `queryClient.clear()` sekwencja „A się wyloguje → B zaloguje się w tej
 * samej karcie" pokazywałaby B listę portfeli A prosto z cache, w ogóle bez
 * odpytania backendu. Backend jest tu poprawny (`get_owned_portfolio`
 * zwraca 404 na cudzy zasób) — to wyciek wyłącznie po stronie klienta.
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";
import { refreshAccessToken } from "@/lib/api";
import { loginRequest, logoutRequest } from "@/lib/auth/authApi";
import {
  getAccessToken,
  setAccessToken,
  subscribeAccessToken,
} from "@/lib/auth/tokenStore";

type AuthContextValue = {
  isAuthenticated: boolean;
  /** `true` do zakończenia startowego silent-refresh — patrz `AuthGuard`. */
  isInitializing: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function getServerSnapshot(): string | null {
  // SSR: token nigdy nie jest znany na serwerze (żyje tylko w pamięci
  // przeglądarki) — pierwszy render zawsze zakłada „niezalogowany".
  return null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const accessToken = useSyncExternalStore(
    subscribeAccessToken,
    getAccessToken,
    getServerSnapshot,
  );
  const [isInitializing, setIsInitializing] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void refreshAccessToken().finally(() => {
      if (!cancelled) setIsInitializing(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await loginRequest(email, password);
      // Kolejność ma znaczenie: czyścimy PRZED ustawieniem tokenu. Odwrotnie
      // `setAccessToken` przerenderowałby konsumentów, ci wystartowaliby
      // zapytania nowego użytkownika, a `clear()` skasowałby ich wyniki w locie.
      queryClient.clear();
      setAccessToken(data.access_token);
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      // W `finally`, bo dane poprzedniego użytkownika muszą zniknąć z pamięci
      // przeglądarki także wtedy, gdy samo `POST /auth/logout` padło.
      setAccessToken(null);
      queryClient.clear();
    }
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: accessToken !== null,
      isInitializing,
      login,
      logout,
    }),
    [accessToken, isInitializing, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth() musi być użyty wewnątrz <AuthProvider>");
  }
  return ctx;
}
