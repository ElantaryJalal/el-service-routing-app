# EL Service — Design System

One product, two surfaces. The office dashboard and the field app must feel
like the same tool in two contexts, so all visual decisions flow from a single
token set defined once and expressed per platform:

| Platform | Token source | Expression |
| --- | --- | --- |
| Office dashboard (Next.js) | `dashboard/app/tokens.css` | CSS custom properties |
| Field app (Expo / RN) | `mobile/src/theme.ts` | Typed theme module |

The two files carry **identical values under matching names** (`--color-brand`
↔ `color.brand`, `--space-4` ↔ `space.s4`). When a value changes, change it in
both files in the same commit.

## Two-surface philosophy

- **Office — calm density.** Managers and dispatchers scan tables, KPIs and
  maps for long stretches. Light neutral surfaces, thin borders, small precise
  type, high information density, nothing that blinks or shouts. Color is
  reserved for *meaning* (status, deltas, the brand accent on primary actions).
- **Field — rugged clarity.** Workers glance at a phone in a parking lot,
  often in sunlight, often with one hand. Same palette and voice, but larger
  tap targets, bigger type steps, stronger contrast between interactive and
  static, and fewer things per screen. Offline states are first-class, not
  error styling.

Both surfaces share: the neutral scale, the single blue accent, the semantic
status colors, the 4px spacing grid, restrained radii, borders-over-shadows,
and quiet motion.

## Color

A cool neutral gray scale does most of the work; **one** brand accent; one
semantic status set used everywhere. Saturation is muted and professional
throughout — status colors are recognisable at a glance without turning the
UI into a traffic light.

### Neutrals (primitives `--el-gray-*`)

| Step | Value | Typical use |
| --- | --- | --- |
| white | `#ffffff` | surface |
| 50 | `#f6f8fb` | app background |
| 100 | `#eef2f7` | chip/soft fills |
| 200 | `#dde4ee` | default border |
| 300 | `#c3cede` | strong border (inputs, buttons) |
| 400 | `#9aa4b2` | placeholder / disabled text |
| 500 | `#5b6b84` | muted text |
| 700 | `#33465f` | secondary emphasis text |
| 900 | `#16233a` | primary text |

Semantic aliases: `--color-bg`, `--color-surface`, `--color-border`,
`--color-border-strong`, `--color-text`, `--color-text-muted`,
`--color-text-faint`.

### Brand accent (one, deep, confident)

| Token | Value | Use |
| --- | --- | --- |
| `--color-brand` / `color.brand` | `#1e40af` | primary buttons, links, active nav, focus |
| `--color-brand-hover` | `#1a3a9e` | hover/pressed |
| `--color-brand-soft` | `#e8eefc` | selected/active fills |
| `--color-brand-ring` | `#dbe5fb` | soft focus halo |
| `--color-on-brand` | `#ffffff` | text/icons on brand |

No second decorative accent exists. The legacy `--accent: #d97706` variable in
`globals.css` is deprecated and unused — do not adopt it.

### Status (lifecycle) — used identically in both apps

| Status | Strong | Soft fill |
| --- | --- | --- |
| draft | `#64748b` | `#eef1f5` |
| planned | `#1d4ed8` | `#e5edff` |
| assigned | `#7c3aed` | `#f1e8ff` |
| in progress | `#b45309` | `#fdf0dd` |
| done | `#15803d` | `#e4f5ea` |
| overdue / problem | `#dc2626` | `#fdf1f1` |

### Feedback (banners, errors, sync notices)

`success`, `warning`, `danger`, `info` — each with `-bg`, `-border`, and
`-text` companions (see `tokens.css`). Success/warning/danger share hues with
done/in-progress/overdue on purpose: one vocabulary of meaning.

### Categorical day/route scale

`--color-day-1..7` / `color.day[]` — the high-contrast cycle for per-day route
lines, markers, and chart series. Not for anything except "which day is this".

## Typography

One clean system sans (`--font-sans`); mono (`--font-mono`) strictly for
tabular numbers (`.num`, KPI deltas, ETAs).

| Token | Size | Weight | Use |
| --- | --- | --- | --- |
| `--text-kpi` | 28 | semibold, tabular | KPI values — distinctly larger and heavier than everything else |
| `--text-xl` | 20 | semibold | page/screen titles |
| `--text-md` | 15 | semibold | section headings (h2) |
| `--text-base` | 14 | regular | body |
| `--text-data` | 13.5 | regular | table cells, dense rows |
| `--text-sm` | 12.5 | regular | secondary text, sub-lines |
| `--text-label` | 12 | semibold, uppercase, `+0.4px` tracking | KPI labels, table headers |
| `--text-xs` | 11.5 | regular | captions, helper notes, provisional tags |

Weights: regular 400 · medium 550 · semibold 650 · bold 700 (RN maps these to
`'400' | '500' | '600' | '700'` — the mapping lives in `theme.ts`).

## Spacing, radius, elevation, motion

- **Spacing:** 4px grid — `--space-1..12` = 4, 8, 12, 16, 20, 24, 32, 48.
  No off-grid paddings in new code.
- **Radius:** `--radius-sm` 6 (buttons, inputs, chips), `--radius-md` 8
  (cards, sheets, map frame), `--radius-full` for pill badges. Nothing else.
- **Elevation:** borders carry structure; shadows stay low. `--shadow-sm` for
  resting cards, `--shadow-md` only for things that float (popovers, sheets).
  Never stack heavy shadows to signal importance.
- **Motion:** `--duration-fast` 150ms for hovers/presses, `--duration-base`
  200ms for reveals/sheet slides, standard easing. No springs, no bounces; the
  global `prefers-reduced-motion` kill-switch stays.

## Using the tokens

Web — reference semantic tokens in CSS (primitives are off-limits to rules):

```css
.thing {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}
```

React Native:

```tsx
import { color, font, space, radius } from '../theme';

const styles = StyleSheet.create({
  card: {
    backgroundColor: color.surface,
    borderColor: color.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: space.s4,
  },
  hint: { color: color.textMuted, fontSize: font.size.sm },
});
```

### Adoption rules

1. **No new literal values.** New or touched styles use tokens; a color/size
   that has no token is a design decision — add the token (both platforms)
   first, or challenge the need.
2. `globals.css` keeps its pre-token variable names (`--bg`, `--primary`,
   `--status-*`, …) as **aliases** into the token layer so nothing shifted
   when tokens landed. New CSS uses the `--color-*` names; the aliases retire
   as screens get touched.
3. Existing hard-coded values in screens (especially the field app, which
   predates the system) are migrated opportunistically — screen by screen,
   never in a big-bang restyle.
4. Status colors always travel as the pair (strong + soft); never invent a
   new tint of a status hue.

### Platform decisions

- The dashboard does **not** use Tailwind; tokens are plain CSS custom
  properties feeding the existing hand-rolled utility classes (`.card`,
  `.btn`, `.badge-*`, …). shadcn/ui was considered and rejected for now: it
  requires Tailwind + a component-layer rewrite, which is exactly the
  framework churn this foundation avoids. Revisit only if a real
  accessibility gap shows up that the current primitives can't cover.
- The field app gets a single `theme.ts` module — no styling library.

## Surface inventory (audit, 2026-07-19)

The screens and recurring elements the tokens must serve. Use this as the
checklist when migrating styles.

### Office dashboard (Next.js) — screens

| Route | Purpose |
| --- | --- |
| `/login` | auth card |
| `/overview` | week KPIs, stops-per-day chart, outstanding markets table |
| `/analytics` | 6-week trend, learned-times table, feedback tags/notes, intro panel |
| `/tours` | tour list table with status badges |
| `/tours/new` | photo upload + extraction draft editor |
| `/tours/[id]` | plan board (day columns, review findings, map, optimise/assign) |
| `/tours/[id]/proof` | per-stop proof-of-work incl. feedback photos |
| `/stores` | catalog table (time spent, provenance, recompute) |
| `/stores/[id]` | store 360: facts, visits ledger, feedback history |

### Office dashboard — recurring elements

Buttons (`.btn`, `-primary`, `-danger`, `-sm`, spinner state) · cards ·
KPI tiles (label/value/sub/note) · status badges (dot pill ×6) ·
provenance badges · tag chips · day chips (colored dot) · data tables
(uppercase headers, hover rows, `.num` mono cells) · editable cell inputs
(+ low-confidence highlight) · type-ahead suggest list · form fields ·
banners (warn/error/ok) · collapsible details panel · demo toggle
(checkbox label) · step dots · nav shell (sticky header, active link) ·
Leaflet map (day markers, route lines) · SVG charts (WeekLoad,
WeeklyTrend) · empty/loading states.

### Field app (Expo) — screens

| Route | Purpose |
| --- | --- |
| `login` | worker sign-in |
| `index` | role gate: worker "My tours" list / office capture home |
| `confirm` | extraction confirm/edit of a captured plan |
| `review` | draft stop review cards |
| `map` / `map.web` | multi-day route map, stop popups, day chips |
| `stores/index`, `stores/[id]` | store list + detail with feedback history |

### Field app — recurring elements

Primary/secondary pressables · screen headers · tour/stop cards
(DraftStopCard, ReviewStopCard, MyToursList rows) · bottom sheets
(CompletionSheet, DayPickerSheet, FeedbackHistorySheet) · tag chips ·
day badges (map + lists) · status/sync notices ("saved on this phone…",
offline queue) · text inputs · feedback entry (tags, note, photo thumb,
"Add photo" button) · map markers/polylines/zoom controls ·
ActivityIndicator loading and empty states.

### Known drift the tokens resolve (when screens migrate)

- Field app blue is `#1f6feb` vs office `#1e40af` → both become
  `color.brand`.
- Field app danger `#b00020`, success `#1a7f37`, warning `#f0b429/#f6a609`
  vs office `#dc2626/#15803d/#b45309` → semantic set wins.
- Field app grays are ad-hoc (`#333`, `#555`, `#777`, `#ccc`, `#eee`, …) →
  neutral scale.
- Day colors already match (defined in `mobile/src/domain/optimisedTour.ts`,
  now also tokens) — dashboard's map should consume the same scale.
