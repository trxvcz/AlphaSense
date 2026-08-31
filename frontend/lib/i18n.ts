/**
 * Konfiguracja językowa (plan krok 50, etap 9).
 *
 * **Polski jest jedynym językiem** i na razie nie ma z czego wybierać.
 * Celem tego kroku jest *struktura*: teksty interfejsu mają mieszkać w
 * katalogu komunikatów, a nie w JSX, żeby dołożenie drugiego języka było
 * dopisaniem pliku, a nie przepisywaniem komponentów.
 *
 * **Świadomie bez segmentu `[locale]` w URL.** next-intl działa w trybie
 * „bez routingu i18n": nie ma `/pl/dashboard`, trasy zostają takie, jakie
 * są. Wprowadzenie prefiksu przy jednym języku oznaczałoby przeniesienie
 * całego `app/` pod `app/[locale]/`, zmianę każdego linku i przekierowania w
 * middleware — koszt duży, korzyść zerowa, dopóki język jest jeden. Gdy
 * dojdzie drugi, ten plik jest miejscem, w którym zaczyna się zmiana.
 */
export const LOCALE = "pl";

/** Strefa czasowa dla formatowania dat po stronie serwera i klienta —
 * bez niej SSR i przeglądarka mogą sformatować tę samą datę inaczej. */
export const TIME_ZONE = "Europe/Warsaw";
