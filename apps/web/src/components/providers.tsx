"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { followSystemTheme } from "@/lib/theme";
import { ToastProvider } from "@/components/ui/toast";

export function Providers({ children }: { children: ReactNode }) {
  // With the "system" theme, switch light/dark live when the operating system does.
  useEffect(() => followSystemTheme(), []);
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            // Retry transient failures only; a 4xx will not get better by retrying.
            retry: (count, error) =>
              count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}
