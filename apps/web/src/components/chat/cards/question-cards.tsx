"use client";

import type {
  ClarificationInteraction,
  ConfirmationInteraction,
  DraftPreview,
} from "@moneymoney/contracts";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { NamedIcon } from "@/components/ui/icons";
import { currencySymbol, todayISO } from "@/lib/format";

export interface InteractionAnswer {
  interactionId: string;
  action: "submit" | "skip" | "cancel";
  value?: string | string[] | null;
}

export type Respond = (answer: InteractionAnswer, label: string) => void;

function DraftLine({ draft }: { draft: DraftPreview }) {
  const parts = [
    draft.description,
    draft.category,
    draft.occurredOnLabel,
    draft.paymentMethod,
  ].filter(Boolean);
  if (!draft.amount && parts.length === 0) return null;
  return (
    <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm text-ink-soft">
      {draft.amount ? (
        <span className={`figure text-lg font-semibold ${draft.type === "income" ? "text-income" : "text-ink"}`}>
          {draft.type === "income" ? "+" : ""}
          {draft.amount.formatted}
        </span>
      ) : null}
      {parts.map((part) => (
        <span key={part}>{part}</span>
      ))}
    </div>
  );
}

function Frame({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <div
      className={`mt-2 rounded-[var(--radius-card)] border p-4 ${
        active ? "border-turmeric/60 bg-turmeric-wash/50" : "border-line bg-paper/60"
      }`}
    >
      {children}
    </div>
  );
}

export function ClarificationCard({
  interaction,
  active,
  onRespond,
}: {
  interaction: ClarificationInteraction;
  active: boolean;
  onRespond: Respond;
}) {
  const [custom, setCustom] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const id = interaction.id;
  const submit = (value: string | string[], label: string) =>
    onRespond({ interactionId: id, action: "submit", value }, label);

  function onCustom(event: FormEvent) {
    event.preventDefault();
    const value = custom.trim();
    if (value) submit(value, value);
  }

  return (
    <Frame active={active}>
      {interaction.draftCount > 1 ? (
        <p className="mb-1 text-xs font-semibold tracking-wide text-ink-faint uppercase">
          Entry {interaction.draftIndex + 1} of {interaction.draftCount}
        </p>
      ) : null}
      {interaction.draft ? <DraftLine draft={interaction.draft} /> : null}
      {!active ? (
        <p className="text-sm text-ink-faint">Answered</p>
      ) : (
        <div className="flex flex-col gap-3">
          {interaction.inputKind === "single_select" ? (
            <div className="flex flex-wrap gap-2" role="group" aria-label={interaction.message}>
              {interaction.options.map((option) => (
                <Button
                  key={option.value}
                  variant="chip"
                  size="sm"
                  icon={option.icon ? <NamedIcon name={option.icon} /> : undefined}
                  onClick={() => submit(option.value, option.label)}
                  title={option.description ?? undefined}
                >
                  {option.label}
                </Button>
              ))}
            </div>
          ) : null}

          {interaction.inputKind === "multi_select" ? (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-2">
                {interaction.options.map((option) => {
                  const on = picked.includes(option.value);
                  return (
                    <Button
                      key={option.value}
                      variant="chip"
                      size="sm"
                      aria-pressed={on}
                      className={on ? "border-lavender-deep bg-lavender-wash" : ""}
                      onClick={() =>
                        setPicked((current) =>
                          on ? current.filter((v) => v !== option.value) : [...current, option.value],
                        )
                      }
                    >
                      {option.label}
                    </Button>
                  );
                })}
              </div>
              <Button
                variant="primary"
                size="sm"
                className="self-start"
                disabled={picked.length === 0}
                onClick={() =>
                  submit(
                    picked,
                    interaction.options.filter((o) => picked.includes(o.value)).map((o) => o.label).join(", "),
                  )
                }
              >
                Done
              </Button>
            </div>
          ) : null}

          {interaction.inputKind === "amount" ? (
            <AmountInput
              currency={interaction.currency ?? "INR"}
              placeholder={interaction.placeholder ?? "Amount"}
              onSubmit={(value) => submit(value, value)}
            />
          ) : null}

          {interaction.inputKind === "date" ? (
            <DateInput max={interaction.maxDate ?? todayISO()} onSubmit={(value, label) => submit(value, label)} />
          ) : null}

          {interaction.inputKind === "text" || (interaction.allowCustomInput && interaction.inputKind === "single_select") ? (
            <form onSubmit={onCustom} className="flex gap-2">
              <label htmlFor={`${id}-custom`} className="sr-only">
                {interaction.placeholder ?? "Your answer"}
              </label>
              <input
                id={`${id}-custom`}
                value={custom}
                onChange={(event) => setCustom(event.target.value)}
                maxLength={64}
                placeholder={interaction.placeholder ?? "Type your answer"}
                className="h-9 min-w-0 flex-1 rounded-[10px] border border-line-strong bg-surface px-3 text-sm focus:border-lavender-deep focus:ring-2 focus:ring-lavender/30 focus:outline-none"
              />
              <Button type="submit" size="sm" disabled={!custom.trim()}>
                Use this
              </Button>
            </form>
          ) : null}

          <div className="flex gap-1">
            {interaction.allowSkip ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onRespond({ interactionId: id, action: "skip" }, "Skip")}
              >
                Skip
              </Button>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRespond({ interactionId: id, action: "cancel" }, "Don't save")}
            >
              Don&apos;t save
            </Button>
          </div>
        </div>
      )}
    </Frame>
  );
}

function AmountInput({
  currency,
  placeholder,
  onSubmit,
}: {
  currency: string;
  placeholder: string;
  onSubmit: (value: string) => void;
}) {
  const [value, setValue] = useState("");
  const clean = value.replace(/,/g, "").trim();
  const valid = /^\d+(\.\d+)?$/.test(clean) && Number(clean) > 0;
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) onSubmit(clean);
      }}
      className="flex gap-2"
    >
      <div className="flex h-10 flex-1 items-center rounded-[10px] border border-line-strong bg-surface px-3 focus-within:border-lavender-deep focus-within:ring-2 focus-within:ring-lavender/30">
        <span className="figure mr-1 text-lg text-ink-faint" aria-hidden>
          {currencySymbol(currency)}
        </span>
        <label htmlFor="clarify-amount" className="sr-only">
          Amount in {currency}
        </label>
        <input
          id="clarify-amount"
          autoFocus
          inputMode="decimal"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={placeholder}
          className="figure min-w-0 flex-1 bg-transparent text-lg focus:outline-none"
        />
      </div>
      <Button type="submit" variant="primary" disabled={!valid}>
        Save amount
      </Button>
    </form>
  );
}

function DateInput({ max, onSubmit }: { max: string; onSubmit: (value: string, label: string) => void }) {
  const [value, setValue] = useState(max);
  const yesterday = (() => {
    const date = new Date(`${max}T00:00:00`);
    date.setDate(date.getDate() - 1);
    const offset = date.getTimezoneOffset() * 60_000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 10);
  })();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="chip" size="sm" onClick={() => onSubmit(max, "Today")}>
        Today
      </Button>
      <Button variant="chip" size="sm" onClick={() => onSubmit(yesterday, "Yesterday")}>
        Yesterday
      </Button>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (value) onSubmit(value, value);
        }}
        className="flex gap-2"
      >
        <label htmlFor="clarify-date" className="sr-only">
          Date
        </label>
        <input
          id="clarify-date"
          type="date"
          value={value}
          max={max}
          onChange={(event) => setValue(event.target.value)}
          className="h-9 rounded-[10px] border border-line-strong bg-surface px-3 text-sm focus:border-lavender-deep focus:outline-none"
        />
        <Button type="submit" size="sm">
          Use this date
        </Button>
      </form>
    </div>
  );
}

export function ConfirmationCard({
  interaction,
  active,
  onRespond,
}: {
  interaction: ConfirmationInteraction;
  active: boolean;
  onRespond: Respond;
}) {
  return (
    <Frame active={active}>
      {interaction.drafts.map((draft, index) => (
        <DraftLine key={index} draft={draft} />
      ))}
      {active ? (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={() =>
              onRespond({ interactionId: interaction.id, action: "submit" }, interaction.confirmLabel)
            }
          >
            {interaction.confirmLabel}
          </Button>
          <Button
            size="sm"
            onClick={() =>
              onRespond({ interactionId: interaction.id, action: "cancel" }, interaction.cancelLabel)
            }
          >
            {interaction.cancelLabel}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-ink-faint">Answered</p>
      )}
    </Frame>
  );
}
