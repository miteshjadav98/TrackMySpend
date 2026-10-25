import type { ApiErrorBody, paths } from "@moneymoney/contracts";
import createClient from "openapi-fetch";

/** Typed client generated from the API's OpenAPI document (same-origin via /api rewrite). */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: Record<string, unknown> | null;

  constructor(status: number, body: Partial<ApiErrorBody> | undefined) {
    const error = body?.error;
    super(error?.message ?? defaultMessage(status));
    this.name = "ApiError";
    this.status = status;
    this.code = error?.code ?? "http_error";
    this.requestId = error?.requestId ?? null;
    this.details = (error?.details as Record<string, unknown> | undefined) ?? null;
  }

  /** The field a validation error is about, if the server named one. */
  get field(): string | null {
    const field = this.details?.["field"];
    return typeof field === "string" ? field : null;
  }
}

function defaultMessage(status: number): string {
  if (status === 0) return "Can't reach MoneyMoney. Check your connection and try again.";
  if (status >= 500) return "Something went wrong on our side. Please try again.";
  return "That didn't work. Please try again.";
}

/**
 * Unwraps an openapi-fetch result: returns data, or throws ApiError with the server's
 * error envelope so every screen shows the same, specific message.
 */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await call;
  } catch {
    throw new ApiError(0, undefined);
  }
  if (!result.response.ok) {
    throw new ApiError(result.response.status, result.error as ApiErrorBody | undefined);
  }
  return result.data as T;
}

export function isUnauthenticated(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** A fresh idempotency key per logical action (reused when that action is retried). */
export function newKey(): string {
  return crypto.randomUUID();
}
