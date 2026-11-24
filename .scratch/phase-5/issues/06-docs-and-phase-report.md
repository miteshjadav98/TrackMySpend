# 06: Phase 5 documentation and verification report

**What to build:** Document reports, charts, deterministic insights and the per-currency policy as
they actually ship, including measured verification and known limits.

Spec: `../spec.md` (all sections).

**Blocked by:** 01, 02, 03, 04, 05

**Status:** ready-for-agent

- [ ] README explains Reports, its period/currency behavior, chat examples and endpoints; the
  roadmap marks Phase 5 built.
- [ ] Architecture documents the reporting read path, cache/failure behavior, chart contract,
  insight rules, performance boundary and currency ADR.
- [ ] GLOSSARY matches final terms in code and UI.
- [ ] `docs/phase-5-report.md` records delivered scope, full checks, query/response measurements,
  live intent eval, accessibility verification, known limits and next steps.
- [ ] `docs/PROGRESS.md` is current and explicitly keeps FX conversion, exports, budgets/forecasts,
  account balances and AG-UI/A2UI out of scope.
- [ ] Final full API/web/build/contract/migration checks pass and their exact results are recorded.

