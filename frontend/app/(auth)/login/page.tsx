import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = {
  title: "Logowanie — AlphaSense",
};

export default function LoginPage() {
  return (
    <section className="flex w-full max-w-sm flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Zaloguj się</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Zobacz skład i wycenę swojego portfela.
        </p>
      </div>
      <LoginForm />
    </section>
  );
}
