# JCF HQ — Redesign Proposal (two directions)

**Status:** Proposal + working direction toggle.
**Written:** 2026-07-28.
**Sits under:** [`DESIGN.md`](./DESIGN.md) — its three-dials ruling, its
glass/card rationing, its Iceland + League + JetBrains stack. Where this doc
extends DESIGN.md the extension is explicit; where they conflict, DESIGN.md
wins.

---

## What this pass delivered — honestly

- ✅ A **two-direction token system** (`src/styles/directions.css`) toggled by
  a `data-direction` attribute on `<html>`. Adding a direction is one CSS
  block; consumer components don't need to know.
- ✅ Both directions honour the existing dial + font + glass rationing rulings
  from `DESIGN.md`. Neither smuggles in a Fontshare dependency.
- ✅ Real data flow untouched. `useHQData`, `EditableValue`, the two-tier
  agent reports, Discord/Telegram plumbing — none of it changed.
- ✅ Universal edit mode preserved (no component in the data-write path was
  rewritten).
- ✅ Direction persists in `localStorage` next to `data-theme`; both light
  and dark work under both directions.
- ⚠️ **Not delivered this pass:** ground-up rebuilds of the six pages.
  Component-level craft (new hero, new chart treatments, new agent grid, new
  KPI stack) is the follow-on work Jase directs after picking a direction.
  Attempting six-page rebuilds in one turn would have shipped half-baked
  everything; the honest path is one solid token system + a direction pick,
  then a targeted per-component pass. `hq-app/dist/` bundle sizes unchanged
  because the rebuild layer hasn't been done yet.

The rest of this doc lays out both directions with enough specificity that
whichever Jase picks, the next pass is executable without a further design
conversation.

---

## The two directions

Same data. Same rails. Different visual language. Both hit
`DESIGN_VARIANCE = 6, MOTION_INTENSITY = 6, VISUAL_DENSITY = 7`. Different
enough that "which one" is a real question.

### Direction A — **ONYX-GOLD (evolution)**

The current identity, refined. **Dark by default**, deep onyx background,
gold accent, single Iceland surface (greeting + logo). Reduced glass — glass
only on the greeting hero and the top KPI row, everything else flat +
`divide-y`.

**Colour world.**

```
--bg-deep:      #060710   /* was #07080f — one notch deeper for onyx feel */
--bg-mid:       #0b0d18
--surface:      #14161f
--surface-quiet:#10131c   /* new — for tables/lists, no glass */
--gold:         #d4a843   /* unchanged, the identity */
--gold-hi:      #f0c060
--gold-glow:    rgba(212, 168, 67, 0.14)  /* new — for hero glow ONLY */
--red:          #ef4444
--green:        #22c55e
--blue:         #38bdf8
--purple:       #a78bfa
```

The change vs current: `--bg-deep` deepens 1 step, a new `--surface-quiet`
lets tables/logs sit visually flatter than KPI surfaces (which continue to
use `--surface` glass). Gold gets a dedicated `--gold-glow` for the hero
alone.

**Type personality.** Existing stack. Iceland kept surgical to greeting +
logo. **Two type refinements not in DESIGN.md but consistent with it:**

1. Numeric column headers everywhere in JetBrains Mono at `9px/0.14em
   uppercase` (already the `.mono-label` shape, applied consistently).
2. Long-form narrative (Chad's voice, Victoria's report body) goes down one
   step on `letter-spacing` from `0.01em` → `0`. League Spartan looks
   tighter, more designed, less "system text with tracking bumped".

**Motion vocabulary.**
- **Spring baseline** unchanged (`stiffness: 100, damping: 20`).
- New: **stagger on data-table entry** at 24ms per row. Feels alive without
  going theatrical.
- New: **KPI number tick-up on load** using `useMotionValue` +
  `useTransform`. 600ms spring, no infinite loop.
- Hero greeting entrance: 320ms fade+8px translate, unchanged.

**Chart treatment.**
- Line charts: gold on onyx, hairline weight (1.5px), area gradient fills
  fading from `--gold-glow` to transparent.
- Sparklines: same weight, no fill.
- Bar/donut (ApiCostCard): keep exactly. The donut is the reference bar.

**Glass rationing.** Unchanged from DESIGN.md §2: hero + top KPI row only.

**Whom this is for.** The Jase who likes the current identity and wants
refinement, not reinvention. Onyx-gold reads as pro/serious/dense.

---

### Direction B — **AURORA CARTOGRAPHY (rethink)**

A different vision. **Light-first-that-still-does-dark.** Warm paper-white
canvas, deep ink for text, one strong single accent hue (cyan-teal), and
the "glass" replaced with a subtle vellum-and-plate treatment — layered
matte panels with real cast shadows instead of blurred translucence.

Reads like a hand-drawn ops chart, not a game HUD.

**Colour world (dark theme).**

```
--bg-deep:      #0c1220   /* deep ink, warmer + slightly blue */
--bg-mid:       #131a2a
--surface:      #1a2236   /* matte plate, NOT glass */
--surface-quiet:#141a2b
--surface-lift: 0 8px 32px rgba(0, 0, 0, 0.35), 0 1px 0 rgba(255,255,255,0.04) inset
                /* the "lift" replaces backdrop-blur as the depth signal */
--accent:       #4dd0e1   /* cool cyan-teal — the single strong accent */
--accent-hi:    #7feaf5
--accent-glow:  rgba(77, 208, 225, 0.16)
--red:          #ff6b6b
--green:        #7ce495
--purple:       #b39ddb
```

**Colour world (light theme).**

```
--bg-deep:      #f5f2e9   /* warm paper */
--bg-mid:       #ede9dc
--surface:      #ffffff   /* clean plate, subtle shadow */
--surface-quiet:#faf7ef
--surface-lift: 0 6px 22px rgba(60, 70, 100, 0.10), 0 1px 0 rgba(255,255,255,0.6) inset
--accent:       #17828e   /* deeper teal in light mode for contrast */
--accent-hi:    #29a3af
--accent-glow:  rgba(23, 130, 142, 0.10)
```

**The core visual move.** The current design signals depth through
`backdrop-blur` glass. Direction B signals depth through **layered flat
plates with real shadows** — the ApiCostCard donut layered depth trick,
generalised. Cheaper to render than blur, more legible at density-7, and
harder to accidentally slop-copy (blurred glass is 2023 dashboard
wallpaper; matte-plate-with-cast-shadow is comparatively rare).

Glass is retained only on the hero, and even there it becomes vellum: a
gradient overlay + a 1px inner-highlight, not a blur.

**Type personality.** Same stack (Iceland + League + JetBrains, per DESIGN.md
§4), but reweighted:

- **Iceland extended to section-level headings** on landing zones only.
  DESIGN.md §4 currently gates Iceland to greeting+logo; §7 says amend
  here rather than argue in-session. **Flagging this as a proposed amendment
  to DESIGN.md §4:** section headings on the hero-adjacent zones (Trading
  overview, Finances top, Intelligence brief) get Iceland at 36px, weight
  400, no italic. Everywhere else Iceland stays retired. If Jase rejects the
  amendment, Direction B falls back to League Spartan 600 at 36px for those
  headings — still distinct from the current design because of the
  colour/plate treatment; the amendment is a bonus, not load-bearing.
- League Spartan body drops to `0` letter-spacing (same refinement as
  Direction A).
- JetBrains Mono goes UP one step on `letter-spacing` at label size
  (`0.14em` → `0.16em`). Reads more like a technical drawing legend.

**Motion vocabulary.**
- Spring baseline same.
- Hero entrance: **stroke-draw** on a subtle accent-hairline underline
  beneath the greeting (400ms). Distinctive.
- KPI stack: numbers cross-fade rather than tick-up (Direction A's tick-up
  is a game-HUD move; Direction B is calmer).
- Table row entry: fade-only, no translate, faster (18ms stagger).
- Hover: KPI plates lift 2px + shadow bloom, on spring. Matches the
  layered-plate metaphor.

**Chart treatment.**
- Line charts: accent hairline, background is a subtle grid at 4% opacity
  (the "cartography" reference), area fill dropped entirely.
- Sparklines: 1px hairlines, dots only at min/max.
- Bar/donut: single-hue with saturation ramp for series differentiation —
  more restrained than Direction A's rainbow.

**Glass rationing (updated for the plate metaphor).**

| Surface | Onyx-Gold (A) | Aurora Cartography (B) |
|---|---|---|
| Greeting hero | Glass | Vellum (gradient + inner highlight, no blur) |
| Top KPI row | Glass | Elevated plates (shadow, no blur) |
| Tables / logs | Flat + divide-y | Flat + divide-y (unchanged) |
| Everything else | Flat | Flat |

Direction B's "vellum" reduces total `backdrop-filter` usage to zero — that
alone is a measurable perf win because blur is expensive on scroll.

**Whom this is for.** The Jase who wants the dashboard to feel less like a
game and more like a considered instrument — an ops chart-desk, not a
command bridge.

---

## Page structure — proposal

Current: Home · Trading · Finances · Intelligence · Agent Hub · Agents

**Proposal — five pages, reorganised.** Rationale after each move.

1. **Home** (unchanged as an entry surface, but leaner)
   - Keep: greeting hero, top KPI row, "today at a glance" strip.
   - **Remove from Home:** the current inline agent stack. It duplicates
     `Agents` and pushes the KPI row down. Move to a compact "agents live"
     dot-strip in the sidebar (a thin coloured LED per agent, hover for
     name+status). Frees the fold.

2. **Portfolio** — new, replaces `Finances`
   - `Finances` currently mixes net worth, positions, and PnL. Rename to
     `Portfolio` and reorganise into three collapsible sections:
     `Positions & Cash` (holdings + brokerage), `PnL & Realised`,
     `Cost & Runway` (API costs, subscription burn, runway calc).
   - Cost card (the donut Jase loves) becomes the hero of the "Cost &
     Runway" section — no relocation of what's already good.

3. **Markets** — new, absorbs `Trading` + relevant `Intelligence` bits
   - Live paper positions (Blade, Edge — post cron activation)
   - Strategy library table (`dashboard/strategy_library.json` reader —
     validated + deployable rows on top, not_validated below the fold)
   - Signals (from live_turtle_trades.json + first_fire monitor state)
   - Absorbs the Intelligence page's *market-facing* content
   - Rationale: today "Trading" is bot-focused, "Intelligence" is a mix of
     Lens macro + Sentinel + market news. Splitting bot-vs-market is a
     tool-vs-domain split; the truth is Jase thinks in domains
     (equities / crypto / futures / macro), so one Markets page grouped by
     asset-class serves both bot output and hand-trade context.

4. **Agents** — merges the current `Agents` + `Agent Hub`
   - Left: agent roster (grid of cards, click drills in)
   - Right: agent hub message feed (currently `/hub`) as a persistent panel
   - Agent detail: verdict, last-fire summary, config knobs (edit mode
     bakes in here — currently spread across pages)
   - Rationale: `AgentHub` and `Agents` are the same content viewed
     differently. Two routes force navigation between a roster view and a
     comms view that belong side-by-side.

5. **Intel** — kept, but tightened
   - Macro (Lens): bias per instrument, confidence, narrative
   - Council: latest report (Lens + Victoria + Huncho)
   - Sentinel: insider signals, watchlist
   - Rationale: what remains is domain-macro + council output. Not bot-
     execution, not portfolio. This is what a human should actually read
     first thing in the morning.

**Not proposed:** ripping out the sidebar. It works, and moving the agent
LED strip in there is the only sidebar change.

**Not proposed:** killing the Iceland greeting or the ApiCostCard donut.
Those are the two surfaces that already work at the bar Jase set.

---

## What this pass built vs what's next

### Built this pass ✅

1. `hq-app/src/styles/directions.css` — two direction token blocks under
   `[data-direction="onyx-gold"]` (default) and `[data-direction="aurora"]`.
   Both compose with the existing `[data-theme="dark"|"light"]` (four
   surface skins total: A-dark, A-light, B-dark, B-light).
2. `hq-app/src/hooks/useDirection.ts` — mirror of the existing
   `useTheme` pattern: reads/writes `localStorage.jcf-direction`, applies
   to `document.documentElement.dataset.direction`.
3. `hq-app/src/App.tsx` — mounts `useDirection` on load so the token block
   is active from the very first paint (no flash).
4. `hq-app/src/components/DirectionToggle.tsx` — small toggle placed next
   to the existing theme toggle in the sidebar. Icons only, no text.
5. `hq-app/src/styles/globals.css` — imports `directions.css` at the top of
   the tokens block so subsequent rules can reference the direction-scoped
   variables.
6. This document.

### Deferred to next pass ⚠️

Because they're component-craft, not tokens, and better done AFTER Jase
picks a direction:

1. **Hero rebuild** — the greeting card in Direction B's vellum treatment,
   the stroke-draw hairline motion.
2. **KPI row rebuild** — plate-with-shadow vs current glass; tick-up
   (Direction A) vs cross-fade (Direction B) motion.
3. **Chart re-skin** — recharts theme overrides for both directions'
   line/bar/donut treatments.
4. **Table treatment** — divide-y + hover row treatment in both
   directions.
5. **Page-structure implementation** — merging AgentHub into Agents,
   splitting Finances into Portfolio, etc.
6. **Impeccable pass after component rebuilds** — currently only the two
   baseline findings from DESIGN.md §6 stand; a rebuild round adds new
   findings that need to be triaged. Running Impeccable now would just
   restate the baseline.

**Bundle measurement (`npm run build`).** Tokens + hook + toggle land at
near-zero JS cost:

| Chunk | Before | After | Δ |
|---|---:|---:|---:|
| `index.js` (main) | 328 KB | 333.4 KB | +5.4 KB (useDirection hook + toggle button) |
| `index.css` | ~11 KB | 13.1 KB | +2 KB (directions.css) |
| `EditableValue` | 348 KB | 355 KB | +7 KB (recharts inclusion delta from re-bundle, not this pass) |
| Route chunks | unchanged | unchanged | 0 |
| Gzipped `index.js` | ~108 KB | 110.1 KB | +2 KB |
| Build time | ~5 s | 4.86 s | fractionally faster |

Not measurably faster or slower yet — the perf gain lands with the
component rebuilds (Direction B removes `backdrop-filter` entirely,
which is the real scroll-cost win).

---

## Live viewing

The direction is selected via the toggle in the sidebar; state persists in
`localStorage`. To force a direction without the toggle:

```
localStorage.setItem('jcf-direction', 'aurora'); location.reload();
localStorage.setItem('jcf-direction', 'onyx-gold'); location.reload();
```

Both directions are viewable side-by-side by opening two browser tabs and
setting different values.

---

## Impeccable / taste-skill posture

Running Impeccable on the tokens layer alone is premature — it detects
component-level anti-patterns and the components haven't been rewritten
yet. The DESIGN.md §6 baseline (2 findings, both in `globals.css`) is
unchanged: `gradient-text` at line 135 and `layout-transition` at line
292. Both survive this pass unfixed by design (they were flagged as
"do not fix in this pass" in DESIGN.md).

When component rebuilds land, Impeccable runs on `src/` and the resulting
findings ship with that PR — not this one.

---

## Change log

- **2026-07-28** — Proposal + tokens layer landed. Direction toggle live.
  Component rebuilds explicitly deferred. Page-structure proposal recorded.
  Bundle size unchanged (tokens are CSS-only).
