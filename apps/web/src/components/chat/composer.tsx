"use client";

import { SendHorizontal, Square } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef } from "react";

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  working,
  answering,
  focusSignal,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  onStop: () => void;
  working: boolean;
  answering: boolean;
  focusSignal: number;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
  }, [value]);

  useEffect(() => {
    if (focusSignal === 0) return;
    const element = ref.current;
    element?.focus();
    element?.setSelectionRange(element.value.length, element.value.length);
  }, [focusSignal]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const text = value.trim();
    if (!text || working) return;
    onSend(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form onSubmit={submit} className="border-t border-line bg-surface px-4 py-3 md:px-8">
      <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-[14px] border border-line-strong bg-surface px-3 py-2 transition-colors focus-within:border-lavender-deep focus-within:ring-2 focus-within:ring-lavender/25">
        <label htmlFor="composer" className="sr-only">
          Message
        </label>
        <textarea
          ref={ref}
          id="composer"
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          maxLength={2000}
          placeholder={
            answering
              ? "Pick an option above, or type your answer"
              : "Spent ₹350 on dinner yesterday, UPI"
          }
          className="max-h-[180px] min-h-[28px] flex-1 resize-none bg-transparent py-1 text-[15px] leading-relaxed placeholder:text-ink-faint focus:outline-none"
        />
        {working ? (
          <button
            type="button"
            onClick={onStop}
            className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-paper text-ink-soft hover:bg-lavender-wash"
            aria-label="Stop waiting for this reply"
            title="Stop waiting"
          >
            <Square className="size-4" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!value.trim()}
            className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-lavender-fill text-white transition-colors hover:bg-lavender-press disabled:bg-line-strong"
            aria-label="Send"
          >
            <SendHorizontal className="size-4" aria-hidden />
          </button>
        )}
      </div>
      <p className="mx-auto mt-1.5 max-w-3xl text-center text-xs text-ink-faint">
        Amounts and totals come from your saved entries. Check a saved entry if something looks off.
      </p>
    </form>
  );
}
