# HQ Dashboard (hq-app)

Jase's personal command center — one web app that replaces checking ~10 tabs
every morning (trading, finances, macro intel, agent status). Lives at
`hq-app/`, served in production by `serve_hq.py`.

## Stack (v3, 2026-07-17 rebuild + Round 1 refinements)
- React 18 + TypeScript + Vite. Deps: `framer-motion`, `recharts`,
  `react-router-dom`.
- **Fonts** (Round 1): Iceland (headers/big numbers, `.head`/`.hero-num`/
  `.stat-num`), League Spartan (body default), Edu NSW ACT Foundation (muted,
  `.soft`), JetBrains Mono (`// labels`, badges, timestamps, terminal).
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

## Agent Hub
The centerpiece — a two-panel iMessage-style chat with every agent, written
**in character** (`src/data/seedMessages.ts`). Send flow: message → typing
dots → canned in-character reply. Runs entirely off seed data (does NOT merge
live `/hq/hub` status logs — those terse lines would clutter the crafted
voice). Roster + voices in `src/data/agentConfig.ts` (mirrors
[[personalities]]; `jarvis` uses `strategist.png`; `edge` has no portrait →
emoji fallback).

## Data binding notes
- Net worth: `net_worth.json` `networth_override` if set, else $958k fallback.
- Blade per-trade **R is computed** (`src/data/derive.ts`) — the learning log
  has no P&L field: `R = (close−entry)/(entry−stop)`, sign-adjusted by
  direction; win = R>0.
- Prefer live data everywhere, spec numbers only as fallback.

## Operations
Served by systemd **user** unit `openclaw-hq.service` (`ExecStart=python3
scripts/serve_hq.py`). Was previously disabled/manual; enabled 2026-07-17 so
it survives reboots. Restart: `systemctl --user restart openclaw-hq`.
Do NOT edit `serve_hq.py` / `hq_storage_server.py` for frontend work.

## Related
- [[system-architecture]] · [[personalities]] · [[cron-schedule]]
- [[../decisions/decision-log]] · [[../sessions/2026-07-17]]
