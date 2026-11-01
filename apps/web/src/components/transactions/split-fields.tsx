"use client";

import type { FriendView, ParticipantInput } from "@moneymoney/contracts";
import Link from "next/link";

import { Input, Select } from "@/components/ui/field";
import { checkExactSplit, minorToText } from "@/lib/split";

/** "you" stands for the user in the amounts map; friends are keyed by their id. */
const YOU = "you";

/** What the user has chosen for a split, before it becomes an API request. */
export interface SplitState {
  /** The friends sharing the expense, besides the user. */
  friendIds: string[];
  /** The friend who paid; empty means the user paid. */
  payerId: string;
  kind: "equal" | "exact";
  /** Typed amounts for an exact split, keyed by "you" or a friend id. */
  amounts: Record<string, string>;
}

export const EMPTY_SPLIT: SplitState = { friendIds: [], payerId: "", kind: "equal", amounts: {} };

/** The people in the split, the user first. */
function peopleKeys(split: SplitState): string[] {
  return [YOU, ...split.friendIds];
}

/** The participants as the API expects them. Amounts are sent only for an exact split. */
export function splitParticipants(split: SplitState): ParticipantInput[] {
  return peopleKeys(split).map((key) => ({
    friendId: key === YOU ? null : key,
    ...(split.kind === "exact" ? { amount: (split.amounts[key] ?? "").replace(/,/g, "").trim() } : {}),
  }));
}

/** Why the split cannot be saved yet, or null when it can. */
export function splitProblem(split: SplitState, total: string, currency: string): string | null {
  if (split.friendIds.length === 0) return "Pick at least one friend to share with.";
  if (split.kind === "exact") {
    const check = checkExactSplit(total, peopleKeys(split).map((key) => split.amounts[key] ?? ""), currency);
    if (!check.addsUp) return "The shares must add up to the total.";
  }
  return null;
}

/** Picks friends, who paid, and how the bill is divided, with a live check on exact amounts. */
export function SplitFields({
  friends,
  split,
  onChange,
  total,
  currency,
  names = {},
}: {
  friends: FriendView[];
  split: SplitState;
  onChange: (next: SplitState) => void;
  total: string;
  currency: string;
  /** Names for friends no longer in the list (archived), so an edit still shows them. */
  names?: Record<string, string>;
}) {
  const friendName = (id: string) => friends.find((friend) => friend.id === id)?.name ?? names[id] ?? "Friend";
  const choices = [
    ...friends.map((friend) => ({ id: friend.id, name: friend.name, email: friend.email })),
    ...split.friendIds
      .filter((id) => !friends.some((friend) => friend.id === id))
      .map((id) => ({ id, name: friendName(id), email: null })),
  ];
  const friendPaid = split.payerId !== "";
  const check =
    split.kind === "exact"
      ? checkExactSplit(total, peopleKeys(split).map((key) => split.amounts[key] ?? ""), currency)
      : null;

  function toggleFriend(id: string, on: boolean) {
    const friendIds = on ? [...split.friendIds, id] : split.friendIds.filter((other) => other !== id);
    onChange({ ...split, friendIds, payerId: friendIds.includes(split.payerId) ? split.payerId : "" });
  }

  function pickPayer(payerId: string) {
    // When a friend paid, only that friend can share with the user.
    onChange({ ...split, payerId, friendIds: payerId ? [payerId] : split.friendIds });
  }

  return (
    <div className="flex flex-col gap-4 rounded-[10px] border border-line bg-paper/60 p-4">
      <fieldset>
        <legend className="text-sm font-medium text-ink-soft">Share with</legend>
        {choices.length === 0 ? (
          <p className="mt-2 text-sm text-ink-faint">
            You have no friends yet. <Link href="/friends" className="text-lavender-ink underline">Add one</Link>.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1.5">
            {choices.map((friend) => (
              <li key={friend.id}>
                <label className="flex items-center gap-2 text-[15px]">
                  <input
                    type="checkbox"
                    checked={split.friendIds.includes(friend.id)}
                    disabled={friendPaid && friend.id !== split.payerId}
                    onChange={(event) => toggleFriend(friend.id, event.target.checked)}
                  />
                  <span>{friend.name}</span>
                  {friend.email ? <span className="text-xs text-ink-faint">{friend.email}</span> : null}
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="split-payer" className="text-sm font-medium text-ink-soft">
            Who paid
          </label>
          <Select id="split-payer" value={split.payerId} onChange={(event) => pickPayer(event.target.value)}>
            <option value="">You</option>
            {split.friendIds.map((id) => (
              <option key={id} value={id}>
                {friendName(id)}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="split-kind" className="text-sm font-medium text-ink-soft">
            Split
          </label>
          <Select
            id="split-kind"
            value={split.kind}
            onChange={(event) => onChange({ ...split, kind: event.target.value as SplitState["kind"] })}
          >
            <option value="equal">Equally</option>
            <option value="exact">Exact amounts</option>
          </Select>
        </div>
      </div>
      {friendPaid ? (
        <p className="-mt-2 text-xs text-ink-faint">When a friend paid, only you and that friend share the expense.</p>
      ) : null}

      {split.kind === "exact" ? (
        <div className="flex flex-col gap-2">
          {peopleKeys(split).map((key) => (
            <div key={key} className="grid grid-cols-[1fr_8rem] items-center gap-3">
              <label htmlFor={`split-amount-${key}`} className="text-[15px]">
                {key === YOU ? "You" : friendName(key)}
              </label>
              <Input
                id={`split-amount-${key}`}
                inputMode="decimal"
                value={split.amounts[key] ?? ""}
                onChange={(event) => onChange({ ...split, amounts: { ...split.amounts, [key]: event.target.value } })}
                placeholder="0"
                className="figure text-right"
              />
            </div>
          ))}
          {check ? (
            <p
              role="status"
              className={`text-sm ${check.addsUp ? "text-income" : "text-danger"}`}
            >
              {check.addsUp
                ? "The shares add up to the total."
                : check.differenceMinor > 0
                  ? `${minorToText(check.differenceMinor, currency)} ${currency} still to assign.`
                  : check.differenceMinor < 0
                    ? `${minorToText(-check.differenceMinor, currency)} ${currency} too much.`
                    : "Every share must be more than zero."}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-ink-faint">
          Everyone pays the same. Any leftover paisa goes to whoever paid.
        </p>
      )}
    </div>
  );
}
