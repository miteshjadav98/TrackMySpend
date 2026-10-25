import type { ApiErrorBody, SendMessageRequest, TurnEvent } from "@moneymoney/contracts";

import { ApiError } from "@/lib/api";

/**
 * Streams one chat turn over Server-Sent Events (POST, so EventSource can't be used).
 *
 * Preflight failures (busy conversation, expired question, rate limit) arrive as normal
 * HTTP errors before the stream starts and are thrown as ApiError. Aborting only stops
 * *listening*: the server finishes the turn, and the reply is there on the next load.
 */
export async function streamTurn(
  conversationId: string,
  body: SendMessageRequest,
  { signal, onEvent }: { signal?: AbortSignal; onEvent: (event: TurnEvent) => void },
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/conversations/${conversationId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0, undefined);
  }
  if (!response.ok || !response.body) {
    let errorBody: ApiErrorBody | undefined;
    try {
      errorBody = (await response.json()) as ApiErrorBody;
    } catch {
      errorBody = undefined;
    }
    throw new ApiError(response.status, errorBody);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = parseBlock(block);
      if (event) onEvent(event);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function parseBlock(block: string): TurnEvent | null {
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    // "event:" duplicates `data.type`; ":" lines are keep-alive comments.
  }
  if (data.length === 0) return null;
  try {
    return JSON.parse(data.join("\n")) as TurnEvent;
  } catch {
    return null;
  }
}
