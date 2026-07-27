"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { registerRequest } from "@/lib/auth/authApi";
import { useAuth } from "@/lib/auth/AuthProvider";
import { validateEmail, validatePassword } from "@/lib/auth/validation";
import { AuthTextField } from "@/components/auth/AuthTextField";

type FieldErrors = {
  email?: string;
  password?: string;
};

export function RegisterForm() {
  const { login } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const emailError = validateEmail(email);
    const passwordError = validatePassword(password);
    setFieldErrors({ email: emailError ?? undefined, password: passwordError ?? undefined });
    if (emailError || passwordError) return;

    setIsSubmitting(true);
    try {
      // Rejestracja nie zwraca tokenów (tylko utworzone konto) — logujemy
      // od razu, żeby użytkownik nie musiał wpisywać hasła drugi raz.
      await registerRequest(email, password);
      await login(email, password);
      router.push("/portfolios");
    } catch (error) {
      setFormError(
        error instanceof ApiError
          ? error.message
          : "Rejestracja nie powiodła się. Spróbuj ponownie.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="flex w-full max-w-sm flex-col gap-4"
    >
      <AuthTextField
        id="email"
        label="E-mail"
        type="email"
        autoComplete="email"
        value={email}
        onChange={setEmail}
        error={fieldErrors.email}
      />
      <AuthTextField
        id="password"
        label="Hasło"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={setPassword}
        error={fieldErrors.password}
      />

      {formError && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {formError}
        </p>
      )}

      <button
        type="submit"
        disabled={isSubmitting}
        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSubmitting ? "Zakładanie konta…" : "Załóż konto"}
      </button>

      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Masz już konto?{" "}
        <Link
          href="/login"
          className="font-medium text-blue-600 outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
        >
          Zaloguj się
        </Link>
      </p>
    </form>
  );
}
