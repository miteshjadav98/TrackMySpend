"use client";

import type { CategoryView, MerchantRuleView } from "@moneymoney/contracts";
import { Search } from "lucide-react";
import { useDeferredValue, useId, useState } from "react";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { useCategories, useMerchantRules, useQueryClient } from "@/lib/queries";

// "Other" and "Other income" mean "I don't know", so a rule never files into them.
const FALLBACK_SLUGS = new Set(["other", "other_income"]);

/** Settings → Merchant rules: see, search, change and forget the rules MoneyMoney has learned. */
export function MerchantRulesSection() {
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const rules = useMerchantRules(deferredSearch);
  const categories = useCategories();
  const items = rules.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <SettingsSection title="Merchant rules" description="Where MoneyMoney files each merchant, learned from what you save.">
      <div className="flex flex-col gap-2 text-sm text-ink-soft">
        <p>
          When you save a transaction with a merchant, MoneyMoney remembers its category and files that merchant&apos;s
          next transaction the same way. A category you pick or name yourself always wins, and becomes the new rule.
          Nothing is learned from &ldquo;Other&rdquo;.
        </p>
        <p>
          Forgetting a rule doesn&apos;t switch learning off: the next transaction you save for that merchant teaches
          it again.
        </p>
      </div>

      <div className="relative mt-5">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
        <label htmlFor="merchant-rule-search" className="sr-only">
          Search merchant rules
        </label>
        <Input
          id="merchant-rule-search"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search merchants"
          className="pl-9"
          maxLength={100}
        />
      </div>

      <div className="mt-4">
        {rules.isPending ? (
          <p className="py-6 text-center text-sm text-ink-faint">Loading rules…</p>
        ) : rules.isError ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <p className="text-sm text-ink-soft">{rules.error.message}</p>
            <Button size="sm" onClick={() => rules.refetch()}>
              Try again
            </Button>
          </div>
        ) : items.length === 0 ? (
          <p className="py-6 text-center text-sm text-ink-soft">
            {deferredSearch
              ? `No merchant matches “${deferredSearch}”.`
              : "No rules yet. Save a transaction with a merchant, like “Swiggy 250”, and its rule appears here."}
          </p>
        ) : (
          <ul aria-label="Merchant rules" className="divide-y divide-line">
            {items.map((rule) => (
              <RuleRow key={rule.id} rule={rule} categories={categories.data ?? []} />
            ))}
          </ul>
        )}
        {rules.hasNextPage ? (
          <div className="mt-4 flex justify-center">
            <Button size="sm" onClick={() => rules.fetchNextPage()} busy={rules.isFetchingNextPage}>
              Show more
            </Button>
          </div>
        ) : null}
      </div>
    </SettingsSection>
  );
}

/** One rule: the merchant and how often it was used, its category picker, and "Forget". */
function RuleRow({ rule, categories }: { rule: MerchantRuleView; categories: CategoryView[] }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const pickerId = useId();
  const [pendingCategoryId, setPendingCategoryId] = useState<string | null>(null);
  const [confirmingForget, setConfirmingForget] = useState(false);
  const [forgetting, setForgetting] = useState(false);

  const choices = categories.filter((c) => c.kind === rule.type && !FALLBACK_SLUGS.has(c.slug));
  // The rule's own category stays in the list, so the picker never shows a different one.
  const current = choices.some((c) => c.id === rule.category.id) ? [] : [rule.category];

  async function changeCategory(categoryId: string) {
    setPendingCategoryId(categoryId);
    try {
      const changed = await unwrap<MerchantRuleView>(
        api.PATCH("/api/v1/merchant-rules/{rule_id}", {
          params: { path: { rule_id: rule.id } },
          body: { categoryId },
        }),
      );
      // Waits for the list to reload, so the picker never flicks back to the old category.
      await queryClient.invalidateQueries({ queryKey: ["merchant-rules"] });
      toast(`${rule.merchant} will be filed under ${changed.category.name} from now on`);
    } catch (caught) {
      toast(caught instanceof ApiError ? caught.message : "That didn't work. Please try again.", { tone: "error" });
    } finally {
      setPendingCategoryId(null);
    }
  }

  async function forget() {
    setForgetting(true);
    try {
      await unwrap(api.DELETE("/api/v1/merchant-rules/{rule_id}", { params: { path: { rule_id: rule.id } } }));
      await queryClient.invalidateQueries({ queryKey: ["merchant-rules"] });
      toast(`Forgot ${rule.merchant}. Its next transaction teaches a new rule.`);
    } catch (caught) {
      toast(caught instanceof ApiError ? caught.message : "That didn't work. Please try again.", { tone: "error" });
      setForgetting(false);
      setConfirmingForget(false);
    }
  }

  return (
    <li className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2">
          <span className="truncate font-medium text-ink">{rule.merchant}</span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
              rule.type === "income" ? "bg-income-wash text-income" : "bg-lavender-wash text-lavender-ink"
            }`}
          >
            {rule.type === "income" ? "Income" : "Expense"}
          </span>
        </p>
        <p className="mt-0.5 text-xs text-ink-faint">
          {rule.timesUsed === 1 ? "Used once" : `Used ${rule.timesUsed} times`} · last used{" "}
          {formatRelative(rule.lastUsedAt)}
        </p>
      </div>

      {confirmingForget ? (
        <div className="flex items-center gap-2">
          <span className="text-sm text-ink-soft">Forget this rule?</span>
          <Button variant="danger" size="sm" onClick={forget} busy={forgetting}>
            Forget it
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirmingForget(false)} disabled={forgetting}>
            Keep
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <label htmlFor={pickerId} className="sr-only">
            Category for {rule.merchant}
          </label>
          <Select
            id={pickerId}
            value={pendingCategoryId ?? rule.category.id}
            onChange={(event) => changeCategory(event.target.value)}
            disabled={pendingCategoryId !== null}
            className="sm:w-48"
          >
            {[...current, ...choices].map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
          <Button variant="ghost" size="sm" onClick={() => setConfirmingForget(true)} className="shrink-0 text-danger">
            Forget
          </Button>
        </div>
      )}
    </li>
  );
}
