"use client";

import type { FriendInviteView, FriendUpdate, FriendView } from "@moneymoney/contracts";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { invalidateFriends, useFriendInvites, useFriends, useQueryClient } from "@/lib/queries";

function asApiError(caught: unknown): ApiError {
  return caught instanceof ApiError ? caught : new ApiError(0, undefined);
}

/** The small line under a friend's name: their email and where their invite stands. */
function friendDetail(friend: FriendView): string {
  const status = friend.isLinked
    ? "Linked"
    : friend.inviteStatus === "pending"
      ? "Invite sent"
      : friend.inviteStatus === "declined"
        ? "Invite declined"
        : null;
  return [friend.email ?? "No email", status].filter(Boolean).join(" · ");
}

/**
 * The Friends page: invites waiting for an answer, the friends list, and a form to add one.
 *
 * Next.js keeps visited pages alive (React `<Activity>`), so nothing here mounts again on a
 * second visit. The effect below runs each time the page is shown, which is when a friend may
 * have accepted or sent an invite since the user was last here.
 */
export function FriendsScreen() {
  const queryClient = useQueryClient();
  const friends = useFriends();
  const invites = useFriendInvites();

  useEffect(() => {
    void invalidateFriends(queryClient);
  }, [queryClient]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-xl flex-col gap-8 px-4 py-6 md:px-8">
        <h1 className="display text-[1.9rem] leading-tight font-semibold">Friends</h1>

        {invites.data?.length ? (
          <section aria-labelledby="invites-heading">
            <h2 id="invites-heading" className="display text-lg font-semibold">
              Invites
            </h2>
            <ul className="mt-3 divide-y divide-line rounded-[var(--radius-card)] border border-line bg-surface px-5 shadow-[var(--shadow-card)]">
              {invites.data.map((invite) => (
                <InviteRow key={invite.id} invite={invite} />
              ))}
            </ul>
          </section>
        ) : null}

        <section aria-labelledby="friends-heading">
          <h2 id="friends-heading" className="display text-lg font-semibold">
            Your friends
          </h2>
          <p className="mt-1 text-ink-soft">
            People you share expenses with. Add an email and, if they use MoneyMoney, they get an invite to link
            up.
          </p>
          <div className="mt-4 rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
            <div className="flex flex-col gap-5">
              {friends.isPending ? (
                <p className="text-sm text-ink-faint">Loading friends…</p>
              ) : friends.isError ? (
                <p role="alert" className="text-sm text-danger">
                  {asApiError(friends.error).message}
                </p>
              ) : friends.data.length === 0 ? (
                <p className="text-sm text-ink-faint">No friends yet. Add one below.</p>
              ) : (
                <ul className="-my-3 divide-y divide-line">
                  {friends.data.map((friend) => (
                    <FriendRow key={friend.id} friend={friend} />
                  ))}
                </ul>
              )}
              <AddFriendForm />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

/** An incoming invite with accept and decline. */
function InviteRow({ invite }: { invite: FriendInviteView }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState<"accept" | "decline" | null>(null);

  async function answer(choice: "accept" | "decline") {
    setBusy(choice);
    try {
      const params = { params: { path: { invite_id: invite.id } } };
      if (choice === "accept") {
        await unwrap<FriendView>(api.POST("/api/v1/friend-invites/{invite_id}/accept", params));
        toast(`You and ${invite.fromName} are now friends`);
      } else {
        await unwrap<unknown>(api.POST("/api/v1/friend-invites/{invite_id}/decline", params));
        toast("Invite declined");
      }
      await invalidateFriends(queryClient);
    } catch (caught) {
      toast(asApiError(caught).message, { tone: "error" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="flex items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{invite.fromName}</p>
        <p className="truncate text-xs text-ink-faint">{invite.fromEmail} wants to link up</p>
      </div>
      <Button
        size="sm"
        variant="ghost"
        busy={busy === "decline"}
        disabled={busy !== null}
        onClick={() => answer("decline")}
        icon={<X className="size-4" aria-hidden />}
      >
        Decline
      </Button>
      <Button
        size="sm"
        variant="primary"
        busy={busy === "accept"}
        disabled={busy !== null}
        onClick={() => answer("accept")}
        icon={<Check className="size-4" aria-hidden />}
      >
        Accept
      </Button>
    </li>
  );
}

/** One friend, with rename/email and remove. A linked friend's email is fixed. */
function FriendRow({ friend }: { friend: FriendView }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    try {
      await unwrap<unknown>(
        api.DELETE("/api/v1/friends/{friend_id}", { params: { path: { friend_id: friend.id } } }),
      );
      await invalidateFriends(queryClient);
      toast(`${friend.name} removed`);
    } catch (caught) {
      toast(asApiError(caught).message, { tone: "error" });
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <li className="py-3">
        <EditFriendForm friend={friend} onDone={() => setEditing(false)} />
      </li>
    );
  }

  return (
    <li className="flex items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{friend.name}</p>
        <p className="truncate text-xs text-ink-faint">{friendDetail(friend)}</p>
      </div>
      {confirmingRemove ? (
        <>
          <span className="text-sm text-ink-soft">Remove?</span>
          <Button size="sm" variant="ghost" onClick={() => setConfirmingRemove(false)} disabled={busy}>
            Keep
          </Button>
          <Button size="sm" variant="danger" busy={busy} onClick={remove}>
            Remove
          </Button>
        </>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash hover:text-ink"
            aria-label={`Edit ${friend.name}`}
            title="Rename or change email"
          >
            <Pencil className="size-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => setConfirmingRemove(true)}
            className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash hover:text-danger"
            aria-label={`Remove ${friend.name}`}
            title="Remove"
          >
            <Trash2 className="size-4" aria-hidden />
          </button>
        </>
      )}
    </li>
  );
}

/** Rename a friend or change their email in place; only what changed is sent. */
function EditFriendForm({ friend, onDone }: { friend: FriendView; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const email = String(form.get("email") ?? "").trim();
    const change: FriendUpdate = {};
    if (name !== friend.name) change.name = name;
    if (!friend.isLinked && email !== (friend.email ?? "")) change.email = email || null;
    if (Object.keys(change).length === 0) {
      onDone();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await unwrap<FriendView>(
        api.PATCH("/api/v1/friends/{friend_id}", {
          params: { path: { friend_id: friend.id } },
          body: change,
        }),
      );
      await invalidateFriends(queryClient);
      onDone();
    } catch (caught) {
      setError(asApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input name="name" aria-label="Friend name" defaultValue={friend.name} maxLength={80} required autoFocus />
        <Input
          name="email"
          type="email"
          aria-label="Friend email"
          placeholder="Email (optional)"
          defaultValue={friend.email ?? ""}
          disabled={friend.isLinked}
          title={friend.isLinked ? "A linked friend's email can't change" : undefined}
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error.message}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button size="sm" type="submit" variant="primary" busy={busy}>
          Save
        </Button>
      </div>
    </form>
  );
}

/** Adds a friend by name, with an optional email that sends an invite. */
function AddFriendForm() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const email = String(form.get("email") ?? "").trim();
    setBusy(true);
    setError(null);
    try {
      const created = await unwrap<FriendView>(
        api.POST("/api/v1/friends", {
          body: { name: String(form.get("name") ?? "").trim(), email: email || null },
        }),
      );
      await invalidateFriends(queryClient);
      formElement.reset();
      toast(`${created.name} added`);
    } catch (caught) {
      setError(asApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4 border-t border-line pt-5">
      <h3 className="font-medium">Add a friend</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          {({ id }) => <Input id={id} name="name" placeholder="Jaymin" maxLength={80} required />}
        </Field>
        <Field label="Email (optional)" hint="Lets us link you if they use MoneyMoney.">
          {({ id, describedBy }) => (
            <Input id={id} name="email" type="email" placeholder="jaymin@example.com" aria-describedby={describedBy} />
          )}
        </Field>
      </div>
      {error ? (
        <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
          {error.message}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" busy={busy} icon={<Plus className="size-4" aria-hidden />}>
          Add friend
        </Button>
      </div>
    </form>
  );
}
