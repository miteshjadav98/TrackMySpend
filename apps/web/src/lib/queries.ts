"use client";

import type {
  AccountView,
  CategoryView,
  ConversationDetail,
  ConversationPage,
  MerchantRulePage,
  MeView,
  SpendingSummary,
  TransactionPage,
  TransactionType,
} from "@moneymoney/contracts";
import {
  type QueryClient,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";

export const keys = {
  me: ["me"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  summary: (period: string) => ["summary", period] as const,
  categories: ["categories"] as const,
  accounts: (includeArchived: boolean) => ["accounts", { includeArchived }] as const,
  transactions: (filters: TransactionFilters) => ["transactions", filters] as const,
  merchantRules: (search: string) => ["merchant-rules", search] as const,
};

/** Anything that changes money: refresh every view that shows totals or rows. */
export function invalidateLedger(client: QueryClient): Promise<unknown> {
  return Promise.all([
    client.invalidateQueries({ queryKey: ["summary"] }),
    client.invalidateQueries({ queryKey: ["transactions"] }),
    client.invalidateQueries({ queryKey: keys.categories }),
    // Every save can teach or use a merchant rule.
    client.invalidateQueries({ queryKey: ["merchant-rules"] }),
  ]);
}

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => unwrap<MeView>(api.GET("/api/v1/me")),
    staleTime: 5 * 60_000,
  });
}

export function useConversations() {
  return useQuery({
    queryKey: keys.conversations,
    queryFn: () =>
      unwrap<ConversationPage>(api.GET("/api/v1/conversations", { params: { query: { limit: 30 } } })),
  });
}

export function useConversation(id: string) {
  return useQuery({
    queryKey: keys.conversation(id),
    queryFn: () =>
      unwrap<ConversationDetail>(
        api.GET("/api/v1/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
  });
}

export function useSummary(period = "this_month") {
  return useQuery({
    queryKey: keys.summary(period),
    queryFn: () =>
      unwrap<SpendingSummary>(
        api.GET("/api/v1/reports/summary", {
          params: { query: { period: period as "this_month" } },
        }),
      ),
  });
}

export function useCategories() {
  return useQuery({
    queryKey: keys.categories,
    queryFn: () => unwrap<CategoryView[]>(api.GET("/api/v1/categories")),
    staleTime: 10 * 60_000,
  });
}

/** The user's accounts, active first: only active ones unless `includeArchived` is set. */
export function useAccounts(includeArchived = false) {
  return useQuery({
    queryKey: keys.accounts(includeArchived),
    queryFn: () =>
      unwrap<AccountView[]>(api.GET("/api/v1/accounts", { params: { query: { includeArchived } } })),
  });
}

/** After any account change: refresh every account list (with and without archived ones). */
export function invalidateAccounts(client: QueryClient): Promise<unknown> {
  return client.invalidateQueries({ queryKey: ["accounts"] });
}

export interface TransactionFilters {
  type?: TransactionType;
  categoryId?: string;
  from?: string;
  to?: string;
  q?: string;
}

export function useTransactions(filters: TransactionFilters) {
  return useInfiniteQuery({
    queryKey: keys.transactions(filters),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap<TransactionPage>(
        api.GET("/api/v1/transactions", {
          params: {
            query: {
              type: filters.type,
              categoryId: filters.categoryId,
              from: filters.from,
              to: filters.to,
              q: filters.q || undefined,
              limit: 50,
              cursor: pageParam,
            },
          },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
}

/** The merchant rules MoneyMoney has learned, most recently used first. */
export function useMerchantRules(search: string) {
  return useInfiniteQuery({
    queryKey: keys.merchantRules(search),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap<MerchantRulePage>(
        api.GET("/api/v1/merchant-rules", {
          params: { query: { q: search || undefined, limit: 50, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
}

export { useQueryClient };
