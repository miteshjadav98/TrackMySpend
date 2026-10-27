# 02: Merchant rules: learn from saves, file the next one

**What to build:** Every saved transaction that has a merchant and a real category teaches a
merchant rule, and the chat uses that rule to file the merchant's next transaction, following
the category precedence in the spec: picked in a clarification > named in the message >
merchant rule > the model's guess > ask. When a rule chose the category, the reply says so
("Filed under Office meals, as before for Swiggy"). No Settings screen yet (ticket 05).

Spec: `../spec.md` → Implementation Decisions → Merchant rules.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A new migration adds the merchant rules table; `alembic check` reports no drift.
- [ ] "swiggy 300" with no rule is saved under the model's guess (Food & Dining), and a Swiggy expense rule exists afterwards.
- [ ] Changing that transaction's category through the API to a custom "Office meals" category updates the rule; the next "swiggy 250" is saved under Office meals with no clarification, and the reply mentions the merchant's usual category.
- [ ] "swiggy 400 groceries" is saved under Groceries (a named category beats the rule), and the rule now points at Groceries.
- [ ] A category picked in a clarification is saved and learned: the next transaction for that merchant is filed without a question.
- [ ] Merchant matching ignores case, punctuation and extra spaces.
- [ ] Expense and income rules are separate.
- [ ] Nothing is learned from a transaction without a merchant, or from the fallback categories (Other, Other income, including a skipped category question).
- [ ] Only a newly inserted transaction teaches: a retried (idempotent) save does not bump the use count.
- [ ] The rule is written in the same database transaction as the save that taught it.
- [ ] Another user's rules never affect this user's saves (isolation test).
- [ ] Unit tests cover merchant key normalisation and all five precedence levels.
- [ ] The new domain module is in the import-linter contract; ruff, mypy --strict, import-linter and the full pytest suite pass.
