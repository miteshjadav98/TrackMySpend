# 01: Settings page as independent sections

**What to build:** The settings page becomes a stack of independent sections that share one
section frame (heading, one-line description, body). Today's profile settings become the first
section and behave exactly as before. Later tickets add Accounts, Merchant rules and Security
by writing one new section file and adding one line to the page. This is a prefactor: nothing
changes for the user.

Spec: `../spec.md` → Implementation Decisions → Web.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The settings page looks and behaves as before; profile fields save as they did.
- [ ] Each section is its own component in its own file; the settings screen only composes sections in order.
- [ ] One shared section-frame component gives every section the same heading, description and body layout.
- [ ] Web typecheck, lint and production build pass.
