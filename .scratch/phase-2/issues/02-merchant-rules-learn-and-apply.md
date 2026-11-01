# 02: Merchant rules: learn from saves, file the next one

**What to build:** Every saved transaction that has a merchant and a real category teaches a
merchant rule, and the chat uses that rule to file the merchant's next transaction, following
the category precedence in the spec: picked in a clarification > named in the message >
merchant rule > the model's guess > ask. When a rule chose the category, the reply says so
("Filed under Office meals, as before for Swiggy"). No Settings screen yet (ticket 05).

Spec: `../spec.md` → Implementation Decisions → Merchant rules.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] A new migration adds the merchant rules table; `alembic check` reports no drift.
- [x] "swiggy 300" with no rule is saved under the model's guess (Food & Dining), and a Swiggy expense rule exists afterwards.
- [x] Changing that transaction's category through the API to a custom "Office meals" category updates the rule; the next "swiggy 250" is saved under Office meals with no clarification, and the reply mentions the merchant's usual category.
- [x] "swiggy 400 groceries" is saved under Groceries (a named category beats the rule), and the rule now points at Groceries.
- [x] A category picked in a clarification is saved and learned: the next transaction for that merchant is filed without a question.
- [x] Merchant matching ignores case, punctuation and extra spaces.
- [x] Expense and income rules are separate.
- [x] Nothing is learned from a transaction without a merchant, or from the fallback categories (Other, Other income, including a skipped category question).
- [x] Only a newly inserted transaction teaches: a retried (idempotent) save does not bump the use count.
- [x] The rule is written in the same database transaction as the save that taught it.
- [x] Another user's rules never affect this user's saves (isolation test).
- [x] Unit tests cover merchant key normalisation and all five precedence levels.
- [x] The new domain module is in the import-linter contract; ruff, mypy --strict, import-linter and the full pytest suite pass.

## Comments

Merged to `phase-2/integration` from branch `phase-2/t02-merchant-rules` (head `b65939b`), in the commit "Merge ticket 02: merchant rules learn from saves and file the next one". Every criterion is met and checked against the code and tests. Checks on the merge: `npm run check:api` clean, `uv run pytest` 164 passed and 1 skipped (the live eval), `alembic check` reports no drift, `npm run contracts` gives no diff (no API change). At the merge, `names_category` was rewritten to name its two tests (whole name, distinctive word) without changing behaviour.

Follow-ups:
- "A rule whose category is archived is ignored" is in `MerchantRuleService.category_for` but untested, because categories cannot be archived yet. Add a test when archiving arrives.
- Ticket 05 can read use counts through `GET /merchant-rules` instead of the service (`tests/integration/test_merchant_rules.py` reads rules through `MerchantRuleService.find` for now).
