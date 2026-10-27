# 01: Settings page as independent sections

**What to build:** The settings page becomes a stack of independent sections that share one
section frame (heading, one-line description, body). Today's profile settings become the first
section and behave exactly as before. Later tickets add Accounts, Merchant rules and Security
by writing one new section file and adding one line to the page. This is a prefactor: nothing
changes for the user.

Spec: `../spec.md` → Implementation Decisions → Web.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] The settings page looks and behaves as before; profile fields save as they did.
- [x] Each section is its own component in its own file; the settings screen only composes sections in order.
- [x] One shared section-frame component gives every section the same heading, description and body layout.
- [x] Web typecheck, lint and production build pass.

## Comments

**Merged** `phase-2/t01-settings-sections` (head `b67e1fc`, work in `43c9826`) into
`phase-2/integration`. The merge was clean and changed only `apps/web/src/components/settings/`.
`npm run check:web` and `npm run build:web` pass.

- `settings-section.tsx` is the shared frame: an `h2` heading tied to the `<section>` by
  `aria-labelledby`, a one-line description, and the card that used to wrap the form.
- `profile-section.tsx` holds the old form unchanged: the same fields, defaults,
  `PATCH /api/v1/me/profile` body, cache update, ledger invalidation, toast and error alert.
- `settings-screen.tsx` keeps the page heading and lists the sections in a column. It is no
  longer a client component; `ProfileSection` is now where client code starts.
- Two small visible differences, both expected from the frame: the card now has a "Profile"
  heading, with the old page description under it as that section's description. The "Settings"
  page title also shows while the profile loads; before, the whole page stayed blank.
