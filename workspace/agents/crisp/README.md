# Crisp — Trading Agent

## Quick Start

Crisp is a specialized sub-agent that executes trades within Jase's ICT + ICC framework.

- **Framework:** Institutional Client Types + Institutional Corrective Constructs
- **Markets:** Forex (primary), Crypto (secondary)
- **Execution:** Driven by framework signals only
- **Reporting:** Structured output to Huncho

## Isolation

Crisp operates in its own workspace: `agents/crisp/`

- No access to Huncho's files
- No shared memory
- Completely isolated state
- All reports routed through Huncho

## How to Use

**Start trading (from Jase via Huncho):**
```
Huncho spawns Crisp on 10-minute cycle
Crisp scans markets, executes clean setups
Reports all activity in structured format
```

**Stop trading:**
```
Huncho receives "stop trading" from Jase
Huncho halts all Crisp spawns
Crisp closes open positions
```

## Files

- `SOUL.md` — Agent philosophy & operating guidelines
- `IDENTITY.md` — Who Crisp is
- `CONFIG.md` — Technical configuration & parameters
- `.openclaw/agent-config.json` — Machine-readable config
- `.openclaw/crisp.log` — Execution log

## Reporting Format

All trade reports use structured format:

```
TRADE_REPORT:
- Pair: [currency pair / crypto pair]
- Setup: [Type of ICT/ICC setup]
- Entry: [Price]
- Stop: [Price]
- Target: [Price]
- Ratio: [Risk:Reward]
- Status: [Executed / Pending / Rejected]
- P&L: [Performance]
- Notes: [Context & confluence]
```

## Safety

- Framework adherence only
- Every trade has a stop order
- No directional bets outside the structure
- Immediate halt on errors
- Clear position limits (set by Jase)

## Next Steps

- Wait for "start trading" command from Jase (via Huncho)
- When active, scan markets on 10-minute cycles
- Report all activity to Huncho
- Honor "stop" commands immediately
