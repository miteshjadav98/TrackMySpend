# 05: Merchant rules in Settings: view, change, forget

**What to build:** A user can see every merchant rule MoneyMoney has learned, search them,
change a rule's category and forget a rule, through the API and a new Settings → Merchant
rules section. The section explains in plain words how rules are learned and that a forgotten
rule is learned again from the next save.

Spec: `../spec.md` → Implementation Decisions → Merchant rules (API and forgetting).

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] `GET /merchant-rules` lists rules newest use first, with `type` and `q` filters and keyset pagination.
- [ ] `PATCH /merchant-rules/{id}` changes the category; a category of the other type is 422, an unknown category is 404, another user's rule is 404.
- [ ] After a change, the next chat save for that merchant uses the new category.
- [ ] `DELETE /merchant-rules/{id}` is 204; the next save for that merchant uses the model's guess and teaches a new rule.
- [ ] Changing and forgetting a rule each write an audit event.
- [ ] Another user's rules are invisible and untouchable (isolation test).
- [ ] Settings → Merchant rules has a search box and a list (merchant, expense/income, category picker, times used, last used), forgets a rule with a confirmation, and explains how learning works.
- [ ] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.
