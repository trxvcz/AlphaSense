/**
 * Walidacja podstawowa formularzy logowania/rejestracji — tylko kształt
 * danych (format e-mail, długość hasła). Reguły biznesowe (e-mail zajęty,
 * złe hasło) zostają po stronie API, formularz pokazuje `error.message`
 * z odpowiedzi (`docs/api-kontrakt.md`, sekcja „Błędy").
 */

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Zgodne z `RegisterIn`/`LoginIn` backendu: `EmailStr`. */
export function validateEmail(email: string): string | null {
  if (email.trim().length === 0) return "Podaj adres e-mail.";
  if (!EMAIL_PATTERN.test(email)) return "Nieprawidłowy format adresu e-mail.";
  return null;
}

/** Zgodne z `RegisterIn.password` backendu: `Field(min_length=8)`. */
export function validatePassword(password: string): string | null {
  if (password.length === 0) return "Podaj hasło.";
  if (password.length < 8) return "Hasło musi mieć minimum 8 znaków.";
  return null;
}
