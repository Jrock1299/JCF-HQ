# HQ Dashboard (hq-app)

Jase's personal command center — one web app that replaces checking ~10 tabs
every morning (trading, finances, macro intel, agent status). Lives at
`hq-app/`, served in production by `serve_hq.py`.

## Stack (v3, 2026-07-17 rebuild + Round 1 & Round 2 refinements)
- React 18 + TypeScript + Vite. Deps: `framer-motion`, `recharts`,
  `react-router-dom`.
- **Fonts** (Round 2 simplification): **Iceland is reserved to two surfaces
  only** — the greeting headline and the "JCF HQ" sidebar logo (`.iceland`
  class). Everything else non-mono is **League Spartan** (`.head`/`.hero-num`/
  `.stat-num`/`.soft` all switched to it). JetBrains Mono unchanged for
  `// labels`, badges, timestamps. **Edu NSW ACT Foundation removed entirely**
  (font import dropped from `index.html`, `--font-soft` var retired).
- **Contrast** (Round 2): muted text bumped for readability — dark
  `--text-dim` 0.55 / `--text-mute` 0.40; light 0.65 / 0.45.
- **Design** (Round 1): solid dark panels (`--surface` rgba(20,22,34,0.85) +
  soft `box-shadow`) instead of transparent glass, moonlight sweep + dialed-back
  orbs, glowing bars/dots/active-nav. All in `src/styles/globals.css`.
- **Light/dark theme**: `data-theme` on `<html>`, tokens flip in `:root` vs
  `:root[data-theme='light']`; `useTheme.ts` persists to localStorage (default
  dark). Top-right control cluster (sun/moon toggle + bell placeholder) in
  `Layout.tsx`, visible on all routes.
- Build: `npm run build` → `vite build` (esbuild, no `tsc` gate so type
  issues never block the build).

## Serving topology (important)
```
browser ──► serve_hq.py (:8899)
              ├─ serves the built SPA from hq-app/dist/
              ├─ serves dashboard/*.json data files directly
              └─ proxies /hq/* ──► hq_storage_server.py (:8900, Flask)
```
The React app fetches **same-origin relative URLs** — never a hardcoded host.
Logical endpoint → URL map lives in `src/hooks/useHQData.ts` (`ENDPOINTS`).
Most data comes from static `dashboard/*.json` files; only `/hq/*` routes hit
the Flask storage server. `useHQData` has a 2.5s timeout + try/catch and
degrades to placeholders — no broken states if `:8900` is down.

## Routes (6)
`/` Home · `/trading` (Blade + Jerry) · `/finances` · `/intelligence` (Lens +
Jarvis) · `/hub` Agent Hub · `/agents`. SPA deep-links work via serve_hq's
index.html fallback.

## Universal edit mode (Round 2)
Every displayed datum is editable in place. `src/edit/EditModeContext.tsx`
provides a global `editing` toggle (persisted; button in the top control
cluster, ✎/✓). `src/components/EditableValue.tsx` wraps any value —
`{file, path, value, type, display}` — and on save writes BOTH a
`localStorage['hq-edit:<file>:<path>']` override (instant + offline fallback)
and `POST /hq/edit/<file>` `{path, value}`. Backend endpoint added to
`hq_storage_server.py` (whitelisted filename, nested dot-path setter, creates
the file if missing). Used across Trading + Finances (balances, stats,
win/loss counts, net worth).

## Floating Huncho assistant (Round 2)
`src/components/HunchoAssistant.tsx`, mounted once in `Layout.tsx` → persists
on every route. Collapsed = circular Huncho portrait + gold glow (bottom
right); expanded = slide-up chat in the Don voice. Route-aware via
`useLocation`. Canned local glossary (compressed regime, R-multiple, ADR, win
rate, drawdown, PF, Sharpe) — UI shell, no live LLM yet.

## Agent Hub
Two-panel iMessage-style chat with every agent, written **in character**
(`src/data/seedMessages.ts`). Send flow: message → typing dots → canned reply.
**Round 2 additions:** a **Group Chat pinned first** (above Huncho, overlapping
portraits) where a message keyword-routes to 2–3 agents who reply staggered;
and **reactions** — double-click any bubble → iOS-style picker (👍❤️😂🔥👀✅) →
corner pill, with agents occasionally reacting in-character to Jase. Roster +
voices + `AGENT_PROFILES` (motto + expanded bio) in `src/data/agentConfig.ts`
(mirrors [[personalities]]; `jarvis` uses `strategist.png`; `edge` → emoji
fallback).

## Agents page (Round 2)
Cards are click-anywhere → **profile modal** (`src/pages/Agents.tsx`): big
gold-ringed portrait, motto, role, status/model badges, connections, expanded
personality, and a Message button → `/hub?agent=<id>`. Closes on X /
click-outside / Escape.

## Data binding notes
- Net worth: `net_worth.json` `networth_override` (now editable in-UI).
- **Trading / Blade (Round 2 reset)**: Blade was reset to a clean slate —
  `blade_balance.json` balance → 0, `blade_learning_log.json` records → `[]`.
  The Trading page no longer renders the clusters table / D3-sizing / circuit
  breaker; it now drives the 4 stat cards + a **win/loss donut ring** +
  layered-depth cards from `blade_balance.json` (balance) and a new
  `blade_manual.json` (`pnl_today`, `win_rate`, `wins`, `losses`, `session`) —
  all editable. Jerry section unchanged.
- **Finances (Round 2 swaps)**: TradeLocker card removed; Trust Wallet →
  **Kraken** (`kraken_data.json` `total_usd`); new **Mercury** business card
  (`mercury_data.json` placeholder, no live API). Monthly cash flow is now a
  gradient **area** chart. Plaid data is stale (last sync 2026-04-20) — not
  fixed, just reported.
- **Intelligence (Round 2 revert)**: rebuilt by adapting the pre-v3
  `Intelligence.jsx` (recovered from commit `e91d5e8`) into the v3 system —
  Daily Brief, Macro Desk (Lens report, driven by `strategy_recommendation`
  instruments + `market_bias`), tabbed Forex/Markets/Crypto feed, and an
  Insider Intelligence (Sentinel, `sentinel_data.json`) block with graceful
  fallbacks.
- `src/data/derive.ts` R-computation helpers remain but Trading no longer uses
  them after the reset (kept for any future re-wire).
- Prefer live data everywhere, spec numbers only as fallback.

## Performance (2026-07-19 pass, commit `eda3787`)
The app felt sluggish. Diagnosis: one monolithic **776 kB / 240 kB gz** JS
bundle (nothing code-split) dominated by `recharts` (pulls the whole `d3-*`
family + `victory-vendor`), which only Trading + Finances use but shipped to
every route. Fixes:
- **Route code-splitting** (`src/App.tsx`): all 6 pages are `React.lazy()` +
  `<Suspense>`. recharts is hoisted into a shared async chunk (~355 kB, bundled
  with `EditableValue` since only those two pages import both) loaded **only** on
  `/trading` and `/finances`. Initial-route JS dropped to **~350 kB / ~117 kB gz**.
- **Blur trim**: `.glass`/tint variants `blur(16px)→8px`, sidebar `20→10`,
  AgentHub panel `16→8`, ChatBubble `12→8`. Surfaces are 85% opaque so the glass
  look is preserved. Orb element blur `48→32px` + `will-change:transform`.
- **Polling**: `useHQData` default `30s → 60s` (all 22 call sites were on the
  default; backend JSON only refreshes every 2–5 min via cron, so 60s still
  over-samples). No 5s intervals existed to keep.
- Already-optimal (left as-is): orbs already animate via `transform` (GPU), and
  `index.html` fonts already carry `&display=swap`.

## Operations
Served by systemd **user** unit `openclaw-hq.service` (`ExecStart=python3
scripts/serve_hq.py`) from `hq-app/dist/` (**gitignored** — rebuild in place on
the VPS: `npm run build` then restart). Was previously disabled/manual; enabled
2026-07-17 so it survives reboots. Restart: `systemctl --user restart openclaw-hq`.
Do NOT edit `serve_hq.py` / `hq_storage_server.py` for frontend work.

## Related
- [[system-architecture]] · [[personalities]] · [[cron-schedule]]
- [[../decisions/decision-log]] · [[../sessions/2026-07-17]]
