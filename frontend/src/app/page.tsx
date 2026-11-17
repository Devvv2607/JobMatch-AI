"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/button";
import { useAuth } from "@/lib/auth";

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" });

export default function AccountPage() {
  const { state, logout } = useAuth();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    if (state.status === "signed-out") router.replace("/login");
  }, [state.status, router]);

  if (state.status !== "signed-in") {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4" aria-busy="true">
        <p className="text-muted" role="status">
          Loading your account…
        </p>
      </main>
    );
  }

  async function onSignOut() {
    setSigningOut(true);
    await logout();
  }

  return (
    <div className="min-h-dvh">
      <header className="border-b border-rule">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-4 px-4">
          <span className="font-serif text-lg">JobMatch</span>
          <div className="flex min-w-0 items-center gap-4">
            <span className="hidden truncate text-sm text-muted sm:inline">{state.user.email}</span>
            <Button variant="quiet" onClick={onSignOut} disabled={signingOut}>
              {signingOut ? "Signing out…" : "Sign out"}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl px-4 py-16">
        <h1 className="font-serif text-4xl leading-tight font-medium tracking-tight sm:text-5xl">
          You’re signed in.
        </h1>
        <dl className="mt-10 grid max-w-md grid-cols-[auto_1fr] gap-x-8 gap-y-3 border-t border-rule pt-6 text-sm">
          <dt className="text-muted">Email</dt>
          <dd className="truncate">{state.user.email}</dd>
          <dt className="text-muted">Member since</dt>
          <dd>{DATE_FORMAT.format(new Date(state.user.created_at))}</dd>
        </dl>
      </main>
    </div>
  );
}
