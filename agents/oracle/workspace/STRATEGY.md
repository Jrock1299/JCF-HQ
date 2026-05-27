# ORACLE — Sports Intelligence Strategy v4

## Core Principle: Only Bet When the Market is Wrong

Oracle does not pick winners. It finds games where the market has mispriced the
true probability. If there's no mispricing, there are no bets. That's correct
behavior — sitting out is a position.

---

## What Changed from v3 (and Why)

| Issue | v3 | v4 |
|---|---|---|
| Markets | H2H moneyline only | ML + Spreads + Totals + Team Totals |
| Pick selection | First +EV h2h | Best EV across all market types per game |
| Spread display | Raw team name | "Lakers -3.5 (SPREAD)" |
| Parlay legs | H2H favorites only | Mixed types from any market |
| Parlay leg floor | -500 | -850 (wider eligibility) |
| Leg type restriction | -500 to -115 (favorites only) | Any odds -850 or better with 58%+ consensus |
| API calls | One call with h2h,spreads,totals | Same call + team_totals (no extra requests) |

**What changed at v3 launch:** moved from noise-based to consensus-based edge detection.

## What Changed from v2 (and Why)

| Issue | v2 | v3 |
|---|---|---|
| Edge detection | DK vs FD disagreement (noise) | Devigged consensus across 8+ books (signal) |
| EV filter | None | Hard requirement: EV must be positive |
| Heavy favorites | No cap | Never worse than -300 |
| Parlays | Always on | Locked until singles hit 52%+ WR |
| Bet sizing | Kelly on fake edge | Kelly on true devigged probability |
| Max exposure | 10% bankroll | 3% bankroll hard cap |
| Sport focus | All sports always | Specializes in best-performing sport after 8+ picks |

**Record at v3 launch: 16W-24L, 40% WR, -$117 P&L** — the v2 system had no edge.

---

## Step 1: Multi-Market Odds Pull (One API Call)

Oracle fetches **all market types in a single Odds API call** per sport:
`markets=h2h,spreads,totals,team_totals`

This minimizes API usage (critical on free tier) while enabling analysis across
every market type simultaneously.

---

## Step 1b: Bet Type Selection Per Game

For every game, Oracle evaluates all available markets:

| Market | Label | Edge Criterion |
|---|---|---|
| H2H moneyline | ML | Devigged consensus prob > implied odds prob |
| Spreads | SPREAD | Same EV logic — point included in display ("Lakers -3.5") |
| Game totals | TOTAL | Same EV logic ("Over 215.5") |
| Team totals | TEAM_TOTAL | Same EV logic per team |

**Oracle picks the SINGLE BEST EV opportunity per game.** A 5% EV spread bet
beats a 2% EV moneyline on the same game — we take the spread.

Each pick is labeled with its type so you always know what you're betting.

---

## Step 2: Consensus Probability (The Truth)

For every game, pull odds from 8 bookmakers: DraftKings, FanDuel, BetMGM,
William Hill, Bovada, MyBookie, BetOnline, PointsBet.

For H2H markets (two outcomes), devig each bookmaker's line:
```
no_vig_P(A) = implied_P(A) / (implied_P(A) + implied_P(B))
```
Average across all books to get **consensus true probability**.

This is our best estimate of the actual probability of each outcome.

---

## Step 2: Expected Value Filter (The Gate)

```
EV = (true_probability × profit_per_unit) − (1 − true_probability) × 1
```

Where `profit_per_unit = decimal_odds − 1`.

**Only picks with EV > 0 qualify.** If the EV is negative, the market is charging
us more than the outcome is worth. We skip it regardless of how confident we feel.

Expressed differently: we only bet when the odds imply a win probability *lower*
than what the consensus of 8 books says the true probability is.

---

## Step 3: Hard Filters

**Maximum line: -300**
Anything shorter has terrible risk/reward. A -1000 bet needs to win 90.9% of the
time just to break even. Even a single loss destroys multiple wins. Structural cap.

**Minimum books: 3**
Need at least 3 books contributing to the consensus. Thin markets = unreliable
consensus = skip.

**Maximum daily picks: 6**
Quality over quantity. A good betting day might have 1-2 plays. If the market is
efficient today, the answer is 0 plays. Never manufacture action.

---

## Step 4: Kelly Criterion (Correct Sizing)

```
f* = (b × p − q) / b
```
Where:
- `b` = decimal odds − 1 (profit per unit)
- `p` = devigged consensus probability (true win estimate)
- `q` = 1 − p

Apply **¼ Kelly** (Kelly × 0.25) for safety margin.

Hard cap: **never exceed 3% of bankroll on one pick**, regardless of Kelly output.

Floor: **$5 minimum** to cover transaction costs.

| Kelly output | Meaning |
|---|---|
| Negative | No mathematical edge — don't bet |
| 0–5% | Small edge — ¼ Kelly may still justify minimum stake |
| 5–15% | Solid edge — ¼ Kelly in normal range |
| 15%+ | Strong edge — capped at 3% bankroll |

---

## Step 5: Sport Specialization

After 8+ resolved picks per sport, Oracle identifies its best-performing sport
and shifts focus there if the win rate is meaningfully above average (+5% edge).

**Rationale:** Edge in sports betting is often sport-specific. A system that works
in NBA line inefficiencies may not work in NFL. Once we identify where the edge is,
concentrate there.

**Re-evaluates** automatically each run as more picks resolve.

---

## Step 6: No Parlays Until Singles Are Profitable

**Parlay unlock condition:** Overall singles win rate ≥ 52% over 20+ resolved picks.

If singles have negative edge, parlays compound that negative edge exponentially.
A parlay of two -EV picks is far worse than either pick alone.

Once singles are profitable, soft parlays run with these rules:

**Mixed-type parlay rules (v4):**
- Legs can be any market type: ML, SPREAD, TOTAL, TEAM_TOTAL
- Mixing types reduces correlation: a spread bet and a total from different games
  are nearly independent outcomes, unlike two H2H picks on correlated games
- **No two legs from the same game** — this automatically prevents correlated
  same-game combos (spread + total from the same game is forbidden)
- Example: `Lakers -3.5 (SPREAD)` + `Celtics/Heat Over 215.5 (TOTAL)` + `Nuggets ML`
- Each leg: -850 or better, consensus probability ≥ 58%
- Combined parlay odds: -175 or better
- Max 2 parlays per day, 2–4 legs each
- Stake: 50% of average single bet stake (min $5)

---

## Step 7: Tracking Everything

Every pick logged to `oracle_record.json`:
- Pick ID, sport, bet type, pick, odds at log time
- Closing odds (for CLV calculation when available)
- CLV = Closing Line Value (positive = we beat the closing line = sharp indicator)
- Result: pending → win / loss / push
- P&L from actual stake

**Tracked metrics:**
- Overall record (W-L, WR%, P&L)
- By sport breakdown
- By bet type (h2h / spreads / totals)
- Average CLV (target: positive over time)
- ROI per sport and bet type

**Bad spot detection:** After 5+ picks in any sport/type with <45% WR,
that category is automatically faded until the sample improves.

---

## Pick Resolution: Odds API Scores

`flashscore_resolver.py` runs every 2 hours (cron). Uses the Odds API
`/v4/sports/{sport}/scores/` endpoint to fetch completed game results and
resolve pending picks by fuzzy team name + date matching.

Updates: `oracle_record.json`, `oracle_picks.json`, `oracle_resolved.json`,
`oracle_bankroll.json`.

---

## Module Architecture

| File | Role |
|---|---|
| `oracle_bot.py` | Main orchestrator, EV analysis, report generation |
| `oracle_intel.py` | Injuries, B2B detection (ESPN API) |
| `oracle_weather.py` | Wind/rain/cold for NFL/MLB outdoor games |
| `oracle_kelly.py` | Kelly sizing (legacy — v3 uses inline true-prob Kelly) |
| `oracle_record.py` | Self-tracking, CLV, bad spot detection |
| `flashscore_resolver.py` | Auto-resolution of pending picks (in /scripts/) |
| `line_cache.json` | Odds history for line movement tracking |
| `oracle_record.json` | Single source of truth for all picks |

---

## Operating Rules

- Oracle does **not** execute bets — picks only
- Telegram report sent after each run (pre-formatted)
- Main cron: 9:00 AM UTC daily
- Resolver cron: every 2 hours
- If zero picks qualify: that's the report. No picks = no bets.
- Treat "no bet day" as a win — capital preserved
