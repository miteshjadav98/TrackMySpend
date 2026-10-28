"use client";

import type {
  ConversationDetail,
  Interaction,
  MessageView,
  SendMessageRequest,
  SuggestedPrompt,
  TurnResult,
} from "@moneymoney/contracts";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ClarificationCard, ConfirmationCard, type Respond } from "@/components/chat/cards/question-cards";
import { SavedCard, SummaryCard, TransactionListCard } from "@/components/chat/cards/result-cards";
import { Composer } from "@/components/chat/composer";
import { TallyStrip } from "@/components/chat/tally-strip";
import { Button } from "@/components/ui/button";
import { NamedIcon } from "@/components/ui/icons";
import { useToast } from "@/components/ui/toast";
import { ApiError, newKey } from "@/lib/api";
import { invalidateLedger, keys, useConversation, useQueryClient } from "@/lib/queries";
import { streamTurn } from "@/lib/sse";

interface LiveTurn {
  clientMessageId: string;
  input: SendMessageRequest["input"];
  label: string;
  phase: "sending" | "streaming" | "failed" | "detached";
  status: string | null;
  text: string;
  error: ApiError | null;
}

const BUSY_PHASES = new Set<LiveTurn["phase"]>(["sending", "streaming"]);

export function ChatView({ conversationId }: { conversationId: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const toast = useToast();
  const detail = useConversation(conversationId);
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [draft, setDraft] = useState("");
  const [focusSignal, setFocusSignal] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const detailKey = keys.conversation(conversationId);

  const applyResult = useCallback(
    (result: TurnResult) => {
      queryClient.setQueryData<ConversationDetail>(detailKey, (current) => {
        if (!current) return current;
        const known = new Set(current.messages.map((message) => message.id));
        const added = [result.userMessage, result.assistantMessage].filter(
          (message): message is MessageView => Boolean(message) && !known.has(message!.id),
        );
        return {
          ...current,
          messages: [...current.messages, ...added],
          pendingInteraction: result.pendingInteraction ?? null,
          suggestions: [],
        };
      });
      if (result.assistantMessage?.ui.some((item) => item.type === "transactions_saved")) {
        void invalidateLedger(queryClient);
      }
      void queryClient.invalidateQueries({ queryKey: keys.conversations });
    },
    [queryClient, detailKey],
  );

  const run = useCallback(
    async (turn: LiveTurn) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setLive({ ...turn, phase: "sending", status: null, text: "", error: null });
      let finished = false;
      try {
        await streamTurn(
          conversationId,
          { clientMessageId: turn.clientMessageId, input: turn.input },
          {
            signal: controller.signal,
            onEvent: (event) => {
              switch (event.type) {
                case "turn.started":
                  setLive((current) => current && { ...current, phase: "streaming" });
                  break;
                case "status":
                  setLive((current) => current && { ...current, status: event.label });
                  break;
                case "text.delta":
                  setLive((current) => current && { ...current, text: current.text + event.delta });
                  break;
                case "turn.completed":
                  finished = true;
                  applyResult(event.result);
                  setLive(null);
                  break;
                case "error":
                  finished = true;
                  setLive(
                    (current) =>
                      current && {
                        ...current,
                        phase: "failed",
                        error: new ApiError(event.retryable ? 503 : 400, {
                          error: { code: event.code, message: event.message, requestId: event.requestId },
                        }),
                      },
                  );
                  break;
                default:
                  break;
              }
            },
          },
        );
        if (!finished) {
          // The connection ended early; the turn still completes on the server.
          setLive((current) => current && { ...current, phase: "detached" });
        }
      } catch (error) {
        if (controller.signal.aborted) {
          setLive((current) => current && { ...current, phase: "detached" });
          return;
        }
        const apiError = error instanceof ApiError ? error : new ApiError(0, undefined);
        if (apiError.status === 401) {
          router.replace("/login");
          return;
        }
        if (apiError.code === "interaction_expired") {
          setLive(null);
          toast("That question was already answered.");
          void queryClient.invalidateQueries({ queryKey: detailKey });
          return;
        }
        setLive((current) => current && { ...current, phase: "failed", error: apiError });
      }
    },
    [conversationId, applyResult, router, toast, queryClient, detailKey],
  );

  const busy = live !== null && BUSY_PHASES.has(live.phase);

  const send = useCallback(
    (input: SendMessageRequest["input"], label: string) => {
      if (busy) return;
      void run({
        clientMessageId: newKey(),
        input,
        label,
        phase: "sending",
        status: null,
        text: "",
        error: null,
      });
    },
    [busy, run],
  );

  const sendText = (text: string) => {
    setDraft("");
    send({ type: "text", text }, text);
  };

  const respond: Respond = (answer, label) =>
    send({ type: "interaction_response", interactionId: answer.interactionId, action: answer.action, value: answer.value ?? null }, label);

  const applyPrompt = (prompt: SuggestedPrompt) => {
    if (prompt.mode === "prefill") {
      setDraft(prompt.prompt);
      setFocusSignal((n) => n + 1);
    } else {
      sendText(prompt.prompt);
    }
  };

  // A detached turn finishes on the server; poll until its reply shows up, then the
  // persisted message replaces the local placeholder.
  const landed =
    live?.phase === "detached" &&
    Boolean(detail.data?.messages.some((m) => m.clientMessageId === live.clientMessageId));
  useEffect(() => {
    if (live?.phase !== "detached" || landed) return;
    const timer = window.setTimeout(() => void queryClient.invalidateQueries({ queryKey: detailKey }), 2500);
    return () => window.clearTimeout(timer);
  }, [live, landed, queryClient, detailKey]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const messages = detail.data?.messages ?? [];
  const pending = detail.data?.pendingInteraction ?? null;
  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 160;
    if (nearBottom || live?.phase === "sending") element.scrollTop = element.scrollHeight;
  }, [messages.length, live?.text, live?.phase]);

  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-ink-soft">{notFound ? "This chat doesn't exist or was deleted." : detail.error.message}</p>
        <Button variant="primary" onClick={() => (notFound ? router.replace("/chat") : detail.refetch())}>
          {notFound ? "Start a new chat" : "Try again"}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TallyStrip />
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto" aria-live="polite" aria-busy={busy}>
        <div className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-6 md:px-8">
          {detail.isPending ? <p className="text-center text-sm text-ink-faint">Loading conversation…</p> : null}

          {!detail.isPending && messages.length === 0 && !live ? (
            <Welcome prompts={detail.data?.suggestions ?? []} onPrompt={applyPrompt} />
          ) : null}

          {messages.map((message) =>
            message.role === "user" ? (
              <UserBubble key={message.id} text={message.content} />
            ) : (
              <AssistantMessage
                key={message.id}
                message={message}
                pendingId={!busy && message.id === lastAssistant?.id ? pending?.id ?? null : null}
                showSuggestions={!live && message.id === lastAssistant?.id}
                onRespond={respond}
                onPrompt={applyPrompt}
              />
            ),
          )}

          {live && !landed ? (
            <>
              <UserBubble text={live.label} faded={live.phase === "sending"} />
              {BUSY_PHASES.has(live.phase) ? (
                <div className="rise-in max-w-[90%]">
                  {live.text ? (
                    <p className="leading-relaxed whitespace-pre-wrap">{live.text}</p>
                  ) : (
                    <p className="flex items-center gap-2 text-sm text-ink-faint">
                      <TypingDots />
                      {live.status ?? "Working on it…"}
                    </p>
                  )}
                </div>
              ) : null}
              {live.phase === "failed" && live.error ? (
                <div role="alert" className="flex flex-wrap items-center gap-3 rounded-[10px] bg-danger-wash px-4 py-3 text-sm text-danger">
                  <span className="flex-1">{live.error.message}</span>
                  <Button size="sm" onClick={() => void run(live)}>
                    Try again
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setLive(null)}>
                    Dismiss
                  </Button>
                </div>
              ) : null}
              {live.phase === "detached" ? (
                <p className="text-sm text-ink-faint">
                  Stopped waiting. The reply will appear here as soon as it&apos;s ready.
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
      <Composer
        value={draft}
        onChange={setDraft}
        onSend={sendText}
        onStop={() => controllerRef.current?.abort()}
        working={busy}
        answering={Boolean(pending) && !busy}
        focusSignal={focusSignal}
      />
    </div>
  );
}

function TypingDots() {
  return (
    <span className="flex gap-1" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span key={i} className="typing-dot size-1.5 rounded-full bg-lavender-deep" style={{ animationDelay: `${i * 0.15}s` }} />
      ))}
    </span>
  );
}

function UserBubble({ text, faded = false }: { text: string; faded?: boolean }) {
  return (
    <div className={`rise-in ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-lavender-fill px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-white ${faded ? "opacity-70" : ""}`}>
      {text}
    </div>
  );
}

function AssistantMessage({
  message,
  pendingId,
  showSuggestions,
  onRespond,
  onPrompt,
}: {
  message: MessageView;
  pendingId: string | null;
  showSuggestions: boolean;
  onRespond: Respond;
  onPrompt: (prompt: SuggestedPrompt) => void;
}) {
  return (
    <div className="rise-in max-w-[92%]">
      <p className="leading-relaxed whitespace-pre-wrap">{message.content}</p>
      {message.ui.map((item) => (
        <InteractionView
          key={item.id}
          item={item}
          active={item.id === pendingId}
          showSuggestions={showSuggestions}
          onRespond={onRespond}
          onPrompt={onPrompt}
        />
      ))}
    </div>
  );
}

/** The only place UI payloads become components: an allowlist keyed by `type`. */
function InteractionView({
  item,
  active,
  showSuggestions,
  onRespond,
  onPrompt,
}: {
  item: Interaction;
  active: boolean;
  showSuggestions: boolean;
  onRespond: Respond;
  onPrompt: (prompt: SuggestedPrompt) => void;
}) {
  switch (item.type) {
    case "clarification":
      return <ClarificationCard interaction={item} active={active} onRespond={onRespond} />;
    case "confirmation":
      return <ConfirmationCard interaction={item} active={active} onRespond={onRespond} />;
    case "transactions_saved":
      return <SavedCard interaction={item} />;
    case "summary":
      return <SummaryCard interaction={item} />;
    case "transaction_list":
      return <TransactionListCard interaction={item} />;
    case "suggestions":
      return showSuggestions ? <Suggestions prompts={item.prompts} onPrompt={onPrompt} /> : null;
    default:
      return null; // unknown types from a newer server are ignored, never rendered raw
  }
}

function Suggestions({ prompts, onPrompt }: { prompts: SuggestedPrompt[]; onPrompt: (prompt: SuggestedPrompt) => void }) {
  if (prompts.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2" aria-label="Suggestions">
      {prompts.map((prompt) => (
        <Button
          key={prompt.label}
          variant="chip"
          size="sm"
          icon={prompt.icon ? <NamedIcon name={prompt.icon} className="size-3.5" /> : undefined}
          onClick={() => onPrompt(prompt)}
        >
          {prompt.label}
        </Button>
      ))}
    </div>
  );
}

function Welcome({ prompts, onPrompt }: { prompts: SuggestedPrompt[]; onPrompt: (prompt: SuggestedPrompt) => void }) {
  return (
    <div className="rise-in py-10">
      <h1 className="display text-[2rem] leading-tight font-semibold">What did you spend today?</h1>
      <p className="mt-2 max-w-lg text-ink-soft">
        Tell me the way you&apos;d tell a friend: &ldquo;₹350 on dinner yesterday, UPI&rdquo;. I&apos;ll file it, and ask
        if something&apos;s missing.
      </p>
      <Suggestions prompts={prompts} onPrompt={onPrompt} />
    </div>
  );
}
