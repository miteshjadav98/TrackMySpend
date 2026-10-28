# Phase 3 brief: split expenses with friends

**Status:** needs-triage (idea captured 2026-10-28; next step is a grilling session, then `to-spec`)

This is the input for Phase 3's design, not the spec. It records what the owner asked for and
the questions the design has to settle.

## What the owner asked for

> "Me and my friend Jaymin spent 1000 on pizza, split it."

- One chat message records the shared expense: who was in it, how it is split, and the
  category, the same way a normal expense is recorded today.
- MoneyMoney keeps that data per person and per category (Splitwise-style).
- If the friend also uses MoneyMoney, the shared expense reaches them: a notification, or it
  shows up in their chat or home page the next time they open the app.

## Why it is a phase of its own

Until now every row belongs to exactly one user, and another user's row is a 404 (`CLAUDE.md`).
A shared expense is the first record two users can both see, so it changes the data model,
the isolation rule and the audit trail, and it adds a notification path. It also needs the
"who owes whom" totals that Phase 2 deliberately left out (no balances yet).

## Questions to settle in the grilling session

**People**
- How is "Jaymin" identified: a friends list keyed by email, an invite link, or a name only?
- Can a friend who has no account be split with (tracked on your side only, linked if they sign up later)?
- Two friends with the same name: how does chat tell them apart?

**The split**
- Who paid? "Me and Jaymin spent 1000" does not say. Ask, or default to "I paid"?
- Split kinds: equal first; exact amounts, percentages and shares later?
- Which amount counts in your spending summaries and category totals: your share (500) or what
  you paid (1000)? Splitwise counts your share.
- Rounding: 1000 / 3 in minor units. Who gets the extra paisa?
- Currency: same currency only in this phase?

**Owing and settling**
- Running balance per friend ("Jaymin owes you 500"), computed in SQL like every other total.
- Settling up ("Jaymin paid me 500"): a new transaction type, or a kind of transfer?
- Groups (a trip, flatmates) now or later?

**The friend's side**
- Does the friend accept before the share lands in their own records, or does it land straight away?
- What does the friend see: only the shared expense, never anything else of yours.
- Edits and deletes after the friend has accepted: who may change what, and how is the other side told?
- Notifications: in-app first (a badge or card on home and in chat, delivered on next visit or
  live over the existing event stream); email or push later?

**Chat and categories**
- Category comes from the same precedence as today (picked > named > merchant rule > guess > ask).
  Does the friend keep the payer's category or get their own merchant rules applied?
- New understanding fields (participants, split kind, payer) mean a new versioned understand prompt and eval cases.

## Terms to add to GLOSSARY.md once settled

Friend, shared expense, share, payer, split, balance (between two friends), settlement.
