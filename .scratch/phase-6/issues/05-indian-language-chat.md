# 05: English, Hinglish and Gujarati chat

**What to build:** Make assistant language explicit, extend exact amount normalisation and localise
the chat path without translating user data or changing financial arithmetic.

Spec: `../spec.md` → Domain model and invariants → Language and voice; User stories →
Indian-language text and voice; Testing and release gates.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Profile supports assistant language `english`, `hinglish` or `gujarati` separately from BCP-47
  formatting locale; Settings explains the distinction.
- [ ] Gujarati digits normalise exactly; a documented bounded vocabulary covers tested lakh/crore,
  hundred/thousand and fractional forms in Latin, Devanagari and Gujarati scripts without guessing
  unsupported ambiguous phrases.
- [ ] Date, currency, account, friend and merchant extraction preserves code-mixed proper names and
  cross-checks model amounts against deterministic normalisation.
- [ ] Owned translations cover chat status, clarifications, confirmations, save/search/summary
  replies and errors; user data and server-produced amounts are never translated or recalculated.
- [ ] The offline parser handles the supported high-precision language cases and remains the outage
  fallback; unsupported language asks a clarification rather than inventing an amount.
- [ ] Prompt and typed schemas carry assistant language without allowing the model to change intent,
  amount, currency, account or server-produced financial values in prose.
- [ ] Unit/eval cases include code-mixed record/search/transfer/share/report/balance/bill/debt
  phrases, Gujarati digits, ambiguous forms and prompt-injection-shaped text.
- [ ] At least five live production-pipeline runs meet the spec's all-money/all-liability and 95%
  overall gates; provider errors and rules fallback are reported separately.
- [ ] Full existing English evaluations remain above their release gate; API/web checks pass.

## Comments

The rest of the application chrome stays English in this phase. “Hinglish” is a product language
choice, not a fake locale code.
