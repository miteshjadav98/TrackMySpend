# Monetary totals stay separate by currency

MoneyMoney stores every amount as exact integer minor units plus an ISO currency. A profile's base
currency supplies a default when the user does not name one; it is not an exchange rate. Reports,
summaries, balances and charts therefore keep monetary values grouped by currency and never add or
compare unlike currencies.

This remains the policy for Phase 5. The Reports page puts the base currency first and lets the user
switch among the currencies present in the period. Counts may be combined because they are not
money. No monetary value is labelled as a base-currency equivalent.

## Considered options

- **Convert every amount using the latest rate.** Rejected: a report would change when viewed later,
  and today's rate does not describe a historical transaction.
- **Convert using the transaction-date rate without storing it.** Rejected: an external provider can
  revise history or become unavailable, so the report would not be reproducible.
- **Let the browser or language model convert for display.** Rejected: financial arithmetic and
  rounding would leave the authoritative server-side domain model.

## Consequences

- A multi-currency report has one exact monetary section per currency and no worldwide grand total.
- Cross-currency transfers and converted friend balances remain unsupported.
- Reconsidering this decision requires a named rate source, stored historical rates, rate dates,
  precision and rounding rules, provider correction behavior and a migration/backfill policy. Only
  then can a converted value be reproduced and audited.

