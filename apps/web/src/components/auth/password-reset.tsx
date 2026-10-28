"use client";

import type { PasswordResetConfirm } from "@moneymoney/contracts";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useLayoutEffect, useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, ApiError, unwrap } from "@/lib/api";

const LINK_CLASS = "font-medium text-lavender-deep underline-offset-2 hover:underline";

/** "Forgot password?": asks for a reset link, and always confirms in the same words. */
export function ForgotPasswordForm() {
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  // Next.js keeps visited pages alive (React <Activity>) instead of unmounting them, so
  // clear the confirmation when the page is hidden; coming back shows a fresh form.
  useLayoutEffect(
    () => () => {
      setSentTo(null);
      setError(null);
    },
    [],
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "");
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/v1/auth/password-reset", { body: { email } }));
      setSentTo(email);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
    } finally {
      setBusy(false);
    }
  }

  if (sentTo !== null) {
    // The server never says whether the account exists, so neither does this page.
    return (
      <>
        <h1 className="display text-[1.9rem] leading-tight font-semibold">Check your email</h1>
        <p className="mt-3 text-ink-soft">
          If there&apos;s an account for <span className="font-medium text-ink">{sentTo}</span>,
          we&apos;ve sent it a link to reset the password. The link works once, for 30 minutes.
        </p>
        <p className="mt-6 text-sm text-ink-soft">
          No email? Check your spam folder, or{" "}
          <button type="button" onClick={() => setSentTo(null)} className={LINK_CLASS}>
            send another link
          </button>
          .
        </p>
        <BackToSignIn />
      </>
    );
  }

  return (
    <>
      <h1 className="display text-[1.9rem] leading-tight font-semibold">Forgot your password?</h1>
      <p className="mt-2 text-ink-soft">
        Enter your email and we&apos;ll send you a link to choose a new one.
      </p>
      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4">
        <Field label="Email">
          {({ id }) => <Input id={id} name="email" type="email" autoComplete="email" required />}
        </Field>
        {error ? <FormError message={error.message} /> : null}
        <Button type="submit" variant="primary" busy={busy} className="mt-2 w-full">
          Send reset link
        </Button>
      </form>
      <BackToSignIn />
    </>
  );
}

/** The token from the emailed link, which travels in the URL fragment (`#token=…`). */
function useTokenFromLink(): string | null | undefined {
  const fragment = useSyncExternalStore(
    (onChange) => {
      window.addEventListener("hashchange", onChange);
      return () => window.removeEventListener("hashchange", onChange);
    },
    () => window.location.hash,
    () => null, // The server never sees the fragment: wait for the browser to read it.
  );
  if (fragment === null) return undefined;
  return new URLSearchParams(fragment.slice(1)).get("token");
}

/** The page the emailed link opens: choose a new password, then sign in with it. */
export function ResetPasswordForm() {
  const token = useTokenFromLink();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState<ApiError | null>(null);
  const [confirmMismatch, setConfirmMismatch] = useState(false);
  const [busy, setBusy] = useState(false);
  // The page stays alive when hidden (see ForgotPasswordForm): clear old errors then.
  useLayoutEffect(
    () => () => {
      setError(null);
      setConfirmMismatch(false);
      setBusy(false);
    },
    [],
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body: PasswordResetConfirm = {
      token: token ?? "",
      newPassword: String(form.get("newPassword") ?? ""),
    };
    setError(null);
    // The confirmation only catches a typo, so it is checked here and never sent.
    const mismatch = body.newPassword !== String(form.get("confirmPassword") ?? "");
    setConfirmMismatch(mismatch);
    if (mismatch) return;

    setBusy(true);
    try {
      await unwrap(api.POST("/api/v1/auth/password-reset/confirm", { body }));
      // Every session was signed out, this browser's included: forget whatever was cached.
      queryClient.clear();
      router.replace("/login?reset=done");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
      setBusy(false);
    }
  }

  if (token === undefined) return null; // still reading the link
  if (token === null || error?.code === "reset_link_invalid") {
    return <InvalidResetLink />;
  }

  const newPasswordError = error?.field === "newPassword" ? error.message : null;
  const formError = error && error.field === null ? error.message : null;
  return (
    <>
      <h1 className="display text-[1.9rem] leading-tight font-semibold">Choose a new password</h1>
      <p className="mt-2 text-ink-soft">
        You&apos;ll be signed out on every device, then you can sign in with the new password.
      </p>
      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4">
        <Field label="New password" hint="At least 10 characters." error={newPasswordError}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              name="newPassword"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              maxLength={128}
              aria-describedby={describedBy}
              aria-invalid={invalid}
            />
          )}
        </Field>
        <Field
          label="Confirm new password"
          error={confirmMismatch ? "The two passwords don't match." : null}
        >
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              name="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              maxLength={128}
              aria-describedby={describedBy}
              aria-invalid={invalid}
            />
          )}
        </Field>
        {formError ? <FormError message={formError} /> : null}
        <Button type="submit" variant="primary" busy={busy} className="mt-2 w-full">
          Set new password
        </Button>
      </form>
      <BackToSignIn />
    </>
  );
}

function InvalidResetLink() {
  return (
    <>
      <h1 className="display text-[1.9rem] leading-tight font-semibold">
        This link doesn&apos;t work
      </h1>
      <p className="mt-3 text-ink-soft">
        Reset links work once and expire after 30 minutes, and only the newest one you asked for
        works. Ask for a new link and use it straight away.
      </p>
      <Link
        href="/forgot-password"
        className="mt-8 inline-flex h-10 w-full items-center justify-center rounded-[10px] bg-lavender-fill px-4 text-[15px] font-medium text-white shadow-sm hover:bg-lavender-press"
      >
        Request a new link
      </Link>
      <BackToSignIn />
    </>
  );
}

function FormError({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
      {message}
    </p>
  );
}

function BackToSignIn() {
  return (
    <p className="mt-6 text-sm text-ink-soft">
      Remembered it?{" "}
      <Link href="/login" className={LINK_CLASS}>
        Back to sign in
      </Link>
    </p>
  );
}
