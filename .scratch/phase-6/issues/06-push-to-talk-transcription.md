# 06: Push-to-talk transcription

**What to build:** Add bounded, private, editable speech transcription to the chat composer through
a provider-neutral backend and Google Cloud Speech-to-Text V2 implementation.

Spec: `../spec.md` → Language and voice; API and contract → Voice; Architecture; Scale, failure and
operations plan.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] `SpeechTranscriber` has a fake test provider and configurable Google Cloud STT V2 provider
  using ADC; startup/config validation does not affect deployments with voice disabled.
- [ ] The authenticated multipart endpoint accepts only probed/allowlisted audio, verifies content,
  enforces 45 seconds and 8 MB, rate/cost limits requests and returns an editable transcript plus
  bounded metadata.
- [ ] Explicit English, Hindi/Hinglish and Gujarati selection maps to validated maintained provider
  language/model/region combinations; no preview automatic detection is a release dependency.
- [ ] Raw audio and transcript text are absent from logs, metrics, database, object storage and
  error reporting; temporary bytes are discarded on success, failure and cancellation.
- [ ] The web requests microphone permission only after a press, probes recording MIME support and
  supports record, stop, cancel, re-record, transcribing and retry states.
- [ ] A successful transcript populates the ordinary composer and is never auto-sent; the user can
  edit or discard it before the existing chat path sees it.
- [ ] Permission denial, unsupported browser, over-limit input, timeout/quota/provider failure and
  offline mode leave typed chat usable and show actionable, translated feedback.
- [ ] API tests use fake audio/provider responses; browser tests cover permission and state flows on
  mobile/desktop, keyboard and screen-reader names. No test calls the paid provider by default.
- [ ] A consented synthetic fixture evaluation meets the spec's exact finance-field gate and records
  provider/model/region, latency and failures without real financial data.
- [ ] Full API/web/build/container checks pass with voice both enabled and disabled.

## Comments

Re-check provider language support and limits when implementation begins. The planning references
were current on 25 November 2026; these are external contracts, not timeless assumptions.
