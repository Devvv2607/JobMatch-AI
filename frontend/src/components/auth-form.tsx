"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/button";
import { TextField } from "@/components/text-field";
import { ApiError, useAuth } from "@/lib/auth";

type Mode = "login" | "register";

const COPY: Record<Mode, { title: string; lede: string; submit: string; busy: string }> = {
  login: {
    title: "Sign in",
    lede: "The few roles worth your time, each with the reason and the gaps.",
    submit: "Sign in",
    busy: "Signing in…",
  },
  register: {
    title: "Create your account",
    lede: "Upload a resume later. For now, an email and a password.",
    submit: "Create account",
    busy: "Creating account…",
  },
};

export function AuthForm({ mode }: { mode: Mode }) {
  const { state, login, register } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const errorId = useId();
  const copy = COPY[mode];

  useEffect(() => {
    if (state.status === "signed-in") router.replace("/");
  }, [state.status, router]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await (mode === "login" ? login : register)(email.trim(), password);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError("Something went wrong.", 0, "unknown"));
      setSubmitting(false);
    }
  }

  // Field errors are shown under their field; anything else goes in the banner.
  const banner = error && Object.keys(error.fields).length === 0 ? error.message : null;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-4 py-12 sm:px-0">
      <p className="font-serif text-lg text-muted">JobMatch</p>
      <h1 className="mt-6 font-serif text-4xl leading-tight font-medium tracking-tight sm:text-5xl">
        {copy.title}
      </h1>
      <p className="mt-3 text-muted">{copy.lede}</p>

      <form
        onSubmit={onSubmit}
        noValidate
        aria-describedby={banner ? errorId : undefined}
        className="mt-10 flex flex-col gap-5"
      >
        {banner && (
          <p
            id={errorId}
            role="alert"
            className="rounded-md border border-danger/30 bg-danger-bg px-3 py-2 text-sm text-danger"
          >
            {banner}
          </p>
        )}
        <TextField
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={setEmail}
          error={error?.fields.email}
        />
        <TextField
          label="Password"
          name="password"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          minLength={mode === "register" ? 10 : undefined}
          hint={mode === "register" ? "At least 10 characters." : undefined}
          value={password}
          onChange={setPassword}
          error={error?.fields.password}
        />
        <Button type="submit" disabled={submitting || state.status === "loading"}>
          {submitting ? copy.busy : copy.submit}
        </Button>
      </form>

      <p className="mt-8 text-sm text-muted">
        {mode === "login" ? (
          <>
            New here?{" "}
            <Link href="/register" className="text-accent underline underline-offset-4">
              Create an account
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link href="/login" className="text-accent underline underline-offset-4">
              Sign in
            </Link>
          </>
        )}
      </p>
    </main>
  );
}
