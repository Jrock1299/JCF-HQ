# JCF HQ — Authoritative Design Direction

**Status:** Binding. **Owner:** Jase. **Established:** 2026-07-25.

Three design skills and one detector are installed against this project, and
they do not fully agree with each other. **This file is the tiebreaker.** When
a skill's guidance conflicts with a rule below, this file wins.

| Source | Role |
|---|---|
| `design-taste-frontend` (taste-skill) | Anti-slop frontend rules + the three dials |
| `high-end-visual-design` (soft-skill) | Awwwards-tier archetypes, motion choreography |
| `redesign-existing-projects` (redesign-skill) | Process: Scan → Diagnose → Fix in place |
| Impeccable (`/impeccable`, + design hook) | Anti-pattern detector, runs after edits |

`redesign-existing-projects` is process-only and conflicts with nothing — it is
the correct entry point for the rebuild. The conflicts are between the two
aesthetic skills, and they are resolved below.

---

## 1. The three dials

Set conversationally per `design-taste-frontend` §1, which states: *"Do not ask
the user to edit this file — overrides happen conversationally."* Recorded here
so they survive the session.

| Dial | Skill baseline | **JCF HQ** | Rationale |
|---|---|---|---|
| `DESIGN_VARIANCE` | 8 | **6** | Pro/neutral command center, not artsy. 8 leans "artsy chaos"; 6 keeps asymmetry available without theatrics. |
| `MOTION_INTENSITY` | 6 | **6** | Unchanged. |
| `VISUAL_DENSITY` | 4 | **7** | Chart-forward dashboard. 4 is "art gallery / airy" — wrong for dense trade and agent data. |

> **Boundary note.** `design-taste-frontend` §216 bans generic card containers
> at `VISUAL_DENSITY > 7`. At exactly **7** that ban does not fire — but §3
> below imposes an equivalent discipline deliberately, so behaviour is the same
> either way. If the dial is ever raised to 8+, §3 and the skill agree without
> further reconciliation.

---

## 2. Glass — rationed, not banned

**The conflict.** `high-end-visual-design` §3.A.1 ("Ethereal Glass") prescribes
*"Vantablack cards with heavy `backdrop-blur-2xl`"* as a primary archetype.
`design-taste-frontend` §0.D lists *"generic glassmorphism on everything"* among
the LLM defaults to reach past. One treats glass as the house style; the other
treats blanket glass as a tell.

**Jase's ruling — neither skill as written:**

JCF HQ **keeps its glass identity**, but glass is a hierarchy signal, not a
default surface.

| Surface | Treatment |
|---|---|
| Greeting / hero | ✅ Glass |
| Headline stat cards (top-level KPIs) | ✅ Glass |
| Tables, trade logs | ❌ Flat + `divide-y` |
| Agent lists, breakdowns | ❌ Flat + `border-t` / negative space |
| Anything nested inside a glass surface | ❌ Never stack glass on glass |

**Rule:** glass earns its place at the top of the hierarchy. It is not applied
by default, and it never stacks. A dense data region rendered as stacked glass
panels is a bug against this document.

*Resolves in favour of:* `design-taste-frontend`'s restraint, while **rejecting**
its implication that glass is inherently slop. *Overrides:*
`high-end-visual-design`'s Ethereal-Glass-everywhere archetype.

---

## 3. Cards — same rule as glass

**The conflict.** `high-end-visual-design` §3.B.1 ("The Asymmetrical Bento")
makes a masonry grid of cards a primary layout. `design-taste-frontend` §214
says *"Use cards ONLY when elevation communicates real hierarchy. Otherwise
group with `border-t`, `divide-y`, or negative space."*

**Jase's ruling:**

- Cards **only** where elevation communicates real hierarchy.
- Lists and dense regions use `divide-y`, `border-t`, or negative space.
- **No cards nested in cards.** Ever.

*Resolves in favour of:* `design-taste-frontend` §214, adopted verbatim.
*Overrides:* `high-end-visual-design`'s Bento-first layout archetype. Bento
remains available for genuinely top-level dashboards; it is not the default for
data regions.

---

## 4. Typography — existing stack stands

**Current stack (verified in `src/styles/globals.css`):**

```css
--font-head: 'Iceland', system-ui, sans-serif;        /* greeting + logo ONLY */
--font-body: 'League Spartan', system-ui, sans-serif; /* body */
--font-mono: 'JetBrains Mono', ui-monospace, monospace; /* data + labels */
```

**Jase's ruling: keep it. Do NOT adopt Clash Display or PP Editorial New.**

`high-end-visual-design` §2 says *"Assume premium fonts like `Geist`, `Clash
Display`, `PP Editorial New`, or `Plus Jakarta Sans` are available."* They are
not available here, and adopting them means taking a **Fontshare dependency**
for no gain — the existing stack already clears both skills' anti-slop bars:

| Check | Source | Status |
|---|---|---|
| Inter / Roboto / Arial / Open Sans / Helvetica banned | `high-end-visual-design` §2 | ✅ **Pass** — none used. (Verified by word-boundary search; earlier substring matches were `inherit` / `interactive`, not the font.) |
| "Inter + slate-900" default rejected | `design-taste-frontend` §0.D | ✅ Pass |
| Mixed-family emphasis is amateur | `design-taste-frontend` §179 | ✅ Pass — mono/sans split is structural (data vs prose), not decorative |

**Serif: no.** `high-end-visual-design` §3.A.2 ("Editorial Luxury") wants
high-contrast variable serif for massive headings. Rejected. The mono/sans split
is the established JCF HQ identity. `design-taste-frontend` §181 already treats
serif as rare-and-justified, so this ruling aligns with it.

**Emphasis:** italic or bold of the *same* family (`design-taste-frontend` §179).
Never inject a serif word into a sans headline.

### ⚠️ Open item — fonts are NOT self-hosted

`design-taste-frontend` §133: *"Always use `next/font` (Next.js) or self-host
with `@font-face` + `font-display: swap`. **Never link Google Fonts via
`<link>` in production.**"*

`index.html` currently loads all three families from `fonts.googleapis.com` via
`<link>` (with `preconnect`). This is a **real violation** of that rule and will
be flagged. It does not change which fonts we use — the ruling above stands —
but self-hosting is outstanding work. (`next/font` does not apply: this is
Vite + React, not Next.js. Self-hosted `@font-face` with `font-display: swap`
is the applicable path.)

Not fixed in this pass — documentation only.

---

## 5. Motion — both skills agree

No conflict to resolve; recorded so it is not relitigated.

- **Spring physics.** `type: "spring", stiffness: 100, damping: 20`
  (`design-taste-frontend` §358).
- **No `linear`. No `ease-in-out`.** (`high-end-visual-design` §2 bans both;
  `design-taste-frontend` §358 bans linear easing. Take the stricter union.)
- **Motion claimed = motion shown.** At `MOTION_INTENSITY: 6`, the page must
  actually animate — entry transitions on hero, scroll-reveal on key sections,
  hover physics on CTAs (`design-taste-frontend` §359).
- **Not every card needs an infinite loop.** Informational sections stay still
  (`design-taste-frontend` §358).
- **`prefers-reduced-motion` is non-negotiable** above `MOTION_INTENSITY: 3`
  (`design-taste-frontend` §526). We are at 6, so it is mandatory.
- **Never `useState` for continuous values** (mouse, scroll, pointer physics) —
  use `useMotionValue` / `useTransform` / `useScroll`
  (`design-taste-frontend` §138).
- **`window.addEventListener("scroll", …)` is banned** — use `useScroll()`,
  ScrollTrigger, IntersectionObserver, or CSS scroll-driven animations
  (`design-taste-frontend` §511).

---

## 6. Known anti-patterns (Impeccable baseline, 2026-07-25)

`npx impeccable detect src/` — **2 findings, unfixed by decision:**

| File | Rule | Detail |
|---|---|---|
| `src/styles/globals.css:135` | `gradient-text` | `background-clip: text` + gradient. Decorative rather than meaningful; a common AI tell on headings and metrics. |
| `src/styles/globals.css:292` | `layout-transition` | `transition: width` causes layout thrash. Use `transform`/`opacity`, or `grid-template-rows` for height. |

Both are pre-existing. Neither was fixed in this pass. The `layout-transition`
finding also violates §5 (motion quality) and should be addressed in the rebuild.

---

## 7. Precedence

There is **no built-in precedence** between the installed skills — they load as
independent peers with zero cross-references, so if two are invoked in one
session both instruction sets sit in context with no arbitration. That is the
reason this file exists.

**Order of authority:**

1. **This file** (`DESIGN.md`)
2. Impeccable detector findings (mechanical, objective)
3. `design-taste-frontend` — the primary aesthetic skill for this project
4. `high-end-visual-design` — consulted for motion choreography and spatial
   rhythm; its Ethereal-Glass and Bento archetypes are **overridden** by §2/§3
5. `redesign-existing-projects` — process, no aesthetic opinions

When a skill contradicts §1–§5, this file wins. Amend here rather than arguing
in-session.

---

## Change log

- **2026-07-25** — Established. Jase resolved the glass and card conflicts
  (rationed, not banned; hierarchy-gated). Dials set to 6 / 6 / 7. Font stack
  confirmed and Fontshare dependency rejected. Serif rejected. Self-hosting
  logged as open work. Impeccable baseline recorded at 2 findings.
