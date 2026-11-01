# 11: Docs and Phase 2 report

**What to build:** The docs describe the system as it now is, so a newcomer can understand
and explain merchant rules, accounts and transfers, and account security without reading the
code first.

Spec: `../spec.md` (all sections).

**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08, 09, 10

**Status:** done

- [x] README: new endpoints, new settings (`WEB_BASE_URL`, reset rate limits), and how to find a reset link in the API log locally.
- [x] `docs/architecture.md`: data model (accounts, transaction accounts, merchant rules, reset tokens), the chat workflow (category precedence, transfers, accounts in chat), auth and security, and the "deliberately not doing yet" table (balances, cross-currency transfers, email provider, two-factor sign-in).
- [x] `GLOSSARY.md` matches the names used in the final code and UI.
- [x] `docs/phase-2-report.md`: what was built against the spec, tests run, live eval numbers, known limitations, next steps.
- [x] `docs/PROGRESS.md` updated.

## Comments

Merged from branch `phase-2/t11-docs` into `phase-2/integration` (merge commit: see the "Merge ticket 11" commit). Spot-checked endpoints, settings and the 332 test count against the code.
