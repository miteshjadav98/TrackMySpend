# 05: Merchant rules in Settings: view, change, forget

**What to build:** A user can see every merchant rule MoneyMoney has learned, search them,
change a rule's category and forget a rule, through the API and a new Settings → Merchant
rules section. The section explains in plain words how rules are learned and that a forgotten
rule is learned again from the next save.

Spec: `../spec.md` → Implementation Decisions → Merchant rules (API and forgetting).

**Blocked by:** 01, 02

**Status:** done

- [x] `GET /merchant-rules` lists rules newest use first, with `type` and `q` filters and keyset pagination.
- [x] `PATCH /merchant-rules/{id}` changes the category; a category of the other type is 422, an unknown category is 404, another user's rule is 404.
- [x] After a change, the next chat save for that merchant uses the new category.
- [x] `DELETE /merchant-rules/{id}` is 204; the next save for that merchant uses the model's guess and teaches a new rule.
- [x] Changing and forgetting a rule each write an audit event.
- [x] Another user's rules are invisible and untouchable (isolation test).
- [x] Settings → Merchant rules has a search box and a list (merchant, expense/income, category picker, times used, last used), forgets a rule with a confirmation, and explains how learning works.
- [x] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.

## Comments

Merged to `phase-2/integration` from branch `phase-2/t05-merchant-rules-settings` (head `cfcca83`), in the commit "Merge ticket 05: merchant rules in Settings (view, change, forget)". The merge was clean; the migration is `0004_merchant_rules_last_used_index` after `0003` and `alembic heads` prints one head. Every criterion is met and checked against the code and tests. Checks on the merge: `npm run check:api` clean, `uv run pytest` 211 passed and 1 skipped (the live eval), `alembic check` reports no drift, `npm run contracts` gives no content diff, `npm run check:web` and `npm run build:web` pass.

Decisions:

- A rule cannot be changed to "Other" or "Other income": `PATCH` answers 422 with "Forget the rule instead." This is the same reason learning skips them ("I don't know" never becomes a rule). The Settings picker leaves those two out.
- The keyset cursor helper in `merchants/service.py` is a local copy of the transactions one. Moving both into one shared helper is a later cleanup.

Follow-ups:

- The web picker hard-codes the fallback slugs (`other`, `other_income`) that the backend also holds in `FALLBACK_SLUGS`; the API stays the authority (422).
