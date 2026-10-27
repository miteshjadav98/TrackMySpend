"use client";

import type { PasswordChange, RevokedSessionsView, SessionView } from "@moneymoney/contracts";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { useQueryClient } from "@/lib/queries";

const SESSIONS_KEY = ["sessions"] as const;

/** Settings → Security: the devices you are signed in on, and your password. */
export function SecuritySection() {
  return (
    <SettingsSection
      title="Security"
      description="See where you're signed in, sign out devices you don't recognise, and change your password."
    >
      <SignedInDevices />
      <hr className="my-6 border-line" />
      <ChangePasswordForm />
    </SettingsSection>
  );
}

function SignedInDevices() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const sessions = useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: () => unwrap<SessionView[]>(api.GET("/api/v1/auth/sessions")),
  });
  // The id of the session being signed out, or "others" while signing out all other devices.
  const [pending, setPending] = useState<string | null>(null);

  async function signOut(session: SessionView) {
    setPending(session.id);
    try {
      await unwrap(
        api.DELETE("/api/v1/auth/sessions/{session_id}", {
          params: { path: { session_id: session.id } },
        }),
      );
      if (session.isCurrent) {
        // Signing out this device is a logout: nothing on this page works any more.
        queryClient.clear();
        router.replace("/login");
        return;
      }
      await queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
      toast(`Signed out ${session.device}`);
    } catch (caught) {
      toast(errorMessage(caught), { tone: "error" });
    } finally {
      setPending(null);
    }
  }

  async function signOutOthers() {
    setPending("others");
    try {
      const { revoked } = await unwrap<RevokedSessionsView>(
        api.POST("/api/v1/auth/sessions/revoke-others"),
      );
      await queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
      toast(revoked === 1 ? "Signed out 1 other device" : `Signed out ${revoked} other devices`);
    } catch (caught) {
      toast(errorMessage(caught), { tone: "error" });
    } finally {
      setPending(null);
    }
  }

  if (sessions.isPending) return <p className="text-sm text-ink-faint">Loading your devices…</p>;
  if (sessions.isError) {
    return (
      <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
        {errorMessage(sessions.error)}
      </p>
    );
  }

  const hasOtherDevices = sessions.data.some((session) => !session.isCurrent);
  return (
    <div>
      <h3 className="font-medium">Where you&apos;re signed in</h3>
      <ul className="mt-2 divide-y divide-line">
        {sessions.data.map((session) => (
          <li key={session.id} className="flex items-center justify-between gap-3 py-3">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 font-medium">
                {session.device}
                {session.isCurrent ? (
                  <span className="rounded-full bg-lavender-wash px-2 py-0.5 text-xs font-medium text-lavender-ink">
                    This device
                  </span>
                ) : null}
              </p>
              <p className="text-sm text-ink-faint">
                {/* Last activity is recorded at most hourly, so this device is simply "now". */}
                {session.isCurrent ? "Active now" : `Last active ${formatRelative(session.lastSeenAt)}`}
                {session.ipAddress ? ` · ${session.ipAddress}` : ""}
              </p>
            </div>
            <Button
              size="sm"
              variant="ghost"
              busy={pending === session.id}
              disabled={pending !== null}
              aria-label={session.isCurrent ? "Sign out of this device" : `Sign out ${session.device}`}
              onClick={() => signOut(session)}
            >
              Sign out
            </Button>
          </li>
        ))}
      </ul>
      {hasOtherDevices ? (
        <Button
          className="mt-3"
          busy={pending === "others"}
          disabled={pending !== null}
          onClick={signOutOthers}
        >
          Sign out all other devices
        </Button>
      ) : (
        <p className="mt-2 text-sm text-ink-faint">You&apos;re not signed in anywhere else.</p>
      )}
    </div>
  );
}

function ChangePasswordForm() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<ApiError | null>(null);
  const [confirmMismatch, setConfirmMismatch] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const body: PasswordChange = {
      currentPassword: String(form.get("currentPassword") ?? ""),
      newPassword: String(form.get("newPassword") ?? ""),
    };
    setError(null);
    // The confirmation only catches a typo, so it is checked here and never sent.
    const mismatch = body.newPassword !== String(form.get("confirmPassword") ?? "");
    setConfirmMismatch(mismatch);
    if (mismatch) return;

    setBusy(true);
    try {
      await unwrap(api.POST("/api/v1/auth/password", { body }));
      formElement.reset();
      await queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
      toast("Password changed. Your other devices have been signed out.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
    } finally {
      setBusy(false);
    }
  }

  // The server names the field it rejects; anything else (too many tries, offline) shows below.
  const errorFor = (field: keyof PasswordChange) => (error?.field === field ? error.message : null);
  const formError = error && error.field === null ? error.message : null;

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <h3 className="font-medium">Change password</h3>
      <Field label="Current password" error={errorFor("currentPassword")}>
        {({ id, describedBy, invalid }) => (
          <Input
            id={id}
            name="currentPassword"
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
            aria-describedby={describedBy}
            aria-invalid={invalid}
          />
        )}
      </Field>
      <Field label="New password" hint="At least 10 characters." error={errorFor("newPassword")}>
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
        error={confirmMismatch ? "The two new passwords don't match." : null}
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
      {formError ? (
        <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
          {formError}
        </p>
      ) : null}
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-ink-faint">Your other devices will be signed out.</p>
        <Button type="submit" variant="primary" busy={busy}>
          Change password
        </Button>
      </div>
    </form>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : new ApiError(0, undefined).message;
}
