# 08: Phase 6 documentation, verification and review

**What to build:** Reconcile the delivered balance/liability/language/voice behavior into public
docs, measure the high-risk paths and review the complete phase before owner acceptance.

Spec: `../spec.md` (all sections).

**Blocked by:** 01, 02, 03, 04, 05, 06, 07

**Status:** ready-for-agent

- [ ] README roadmap and usage explain anchors, known vs unknown balances, bills, debt plans,
  supported chat languages, voice review and the no-audio-retention promise.
- [ ] Architecture documents cash effects, payment allocation, language/transcription boundaries,
  provider failure, privacy metadata, scale triggers and configuration.
- [ ] GLOSSARY and ADR 0003 match shipped names and invariants; any implementation departure is
  resolved in code/docs rather than left contradictory.
- [ ] `docs/phase-6-report.md` records delivered scope, migrations, full commands/results, known
  limits, live text/voice evaluations, privacy verification and next steps.
- [ ] `docs/PROGRESS.md` records branch/merge/publish state exactly and a reproducible local owner
  acceptance flow.
- [ ] A 100,000-movement account benchmark measures current balance and paginated history; bill
  allocation race tests and speech latency/cost-limit results are recorded.
- [ ] Full Python/web checks, all tests, contracts, migration drift, production build, both
  container builds and hosted CI pass; opt-in/provider skips are named, not reported as green.
- [ ] A senior review of `phase-6/integration` finds correctness, security/privacy, performance,
  contract, architecture and test gaps; blocking findings are fixed in this ticket.
- [ ] Local desktop/mobile, light/dark, keyboard and microphone acceptance is ready for the owner;
  the branch is not merged to main until accepted.

## Comments

The final report must distinguish transcript accuracy from end-to-end financial-field accuracy.
Word error rate alone is not a release criterion.
