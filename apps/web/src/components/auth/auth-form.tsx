"use client";

import type { MeView } from "@moneymoney/contracts";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, ApiError, unwrap } from "@/lib/api";
import { keys } from "@/lib/queries";

function detectedTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  } catch {
    return "Asia/Kolkata";
  }
}

function safeNext(value: string | null): string {
  // Only same-site paths: never redirect to an attacker-supplied absolute URL.
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/chat";
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setBusy(true);
    setError(null);
    try {
      const me =
        mode === "login"
          ? await unwrap<MeView>(api.POST("/api/v1/auth/login", { body: { email, password } }))
          : await unwrap<MeView>(
              api.POST("/api/v1/auth/register", {
                body: {
                  email,
                  password,
                  displayName: String(form.get("displayName") ?? ""),
                  timezone: detectedTimezone(),
                  baseCurrency: "INR",
                  locale: "en-IN",
                },
              }),
            );
      queryClient.clear();
      queryClient.setQueryData(keys.me, me);
      router.replace(safeNext(params.get("next")));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
      setBusy(false);
    }
  }

  // The reset-password page sends the user here once their new password is set.
  const passwordWasReset = mode === "login" && params.get("reset") === "done";
  const formError = error
    ? error.code === "validation_failed" && error.field === null
      ? "Check the email address and password, then try again."
      : error.message
    : null;

  return (
    <>
      <h1 className="display text-[1.9rem] leading-tight font-semibold">
        {mode === "login" ? "Sign in" : "Create your account"}
      </h1>
      <p className="mt-2 text-ink-soft">
        {mode === "login"
          ? "Pick up where you left off."
          : "Track spending by typing it, the way you'd text a friend."}
      </p>
      {passwordWasReset ? (
        <p
          role="status"
          className="mt-6 rounded-[10px] bg-lavender-wash px-3 py-2 text-sm text-lavender-ink"
        >
          Password changed. You&apos;ve been signed out everywhere, so sign in with your new
          password.
        </p>
      ) : null}
      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4" noValidate={false}>
        {mode === "register" ? (
          <Field label="Your name">
            {({ id }) => (
              <Input id={id} name="displayName" autoComplete="name" required maxLength={100} />
            )}
          </Field>
        ) : null}
        <Field label="Email">
          {({ id, invalid }) => (
            <Input
              id={id}
              name="email"
              type="email"
              autoComplete="email"
              required
              aria-invalid={invalid}
            />
          )}
        </Field>
        <Field label="Password" hint={mode === "register" ? "At least 10 characters." : undefined}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              name="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 10 : undefined}
              maxLength={128}
              aria-describedby={describedBy}
              aria-invalid={invalid}
            />
          )}
        </Field>
        {mode === "login" ? (
          <Link
            href="/forgot-password"
            className="-mt-2 self-end text-sm font-medium text-lavender-deep underline-offset-2 hover:underline"
          >
            Forgot password?
          </Link>
        ) : null}
        {formError ? (
          <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
            {formError}
          </p>
        ) : null}
        <Button type="submit" variant="primary" busy={busy} className="mt-2 w-full">
          {mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>
      <p className="mt-6 text-sm text-ink-soft">
        {mode === "login" ? "New here? " : "Already have an account? "}
        <Link
          href={mode === "login" ? "/register" : "/login"}
          className="font-medium text-lavender-deep underline-offset-2 hover:underline"
        >
          {mode === "login" ? "Create an account" : "Sign in"}
        </Link>
      </p>
    </>
  );
}
