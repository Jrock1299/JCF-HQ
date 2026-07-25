#!/usr/bin/env python3
"""
One-shot: standardize JCF HQ cron to America/New_York wall-clock times.

WHY THE GUARD PATTERN
---------------------
Two mechanisms were tried and rejected, both empirically:

  TZ=America/New_York   — INERT for scheduling on this build. `man 5 crontab`:
                          "Even if a user specifies the TZ environment variable
                          in his crontab this will affect only the commands
                          executed in the crontab, not the execution of the
                          crontab tasks themselves."

  CRON_TZ=America/New_York — NOT SUPPORTED. This is a cronie (RHEL) feature.
                          Ubuntu ships vixie-cron 3.0pl1; `CRON_TZ` does not
                          appear in the binary or the man page. A probe entry
                          scheduled via CRON_TZ never fired.

What DOES work — and is what the crontab man page itself recommends — is to
schedule at BOTH candidate UTC hours and let the job check ET before running:

    0 12,13 * * *  [ "$(TZ=America/New_York date +\\%H:\\%M)" = "08:00" ] && cmd

EDT: 12:00 UTC = 08:00 ET -> runs;  13:00 UTC = 09:00 ET -> skipped.
EST: 12:00 UTC = 07:00 ET -> skipped; 13:00 UTC = 08:00 ET -> runs.

The correct one fires in either season, so the November DST shift needs no
edit. Verified live before adoption (probe fired 16:45:01 UTC = 12:45 ET).
"""

import re
import subprocess
import sys

# ET wall-clock target -> (utc_hours_to_try, et_guard_string)
#   EDT = UTC-4, EST = UTC-5, so each ET hour maps to two candidate UTC hours.
SLOTS = {
    "08:00": ("12,13", "08:00"),   # 8 AM ET
    "09:00": ("13,14", "09:00"),   # 9 AM ET
    "20:00": ("0,1",   "20:00"),   # 8 PM ET (rolls into next UTC day; daily job)
}


def guard(et_time: str) -> str:
    return f'[ "$(TZ=America/New_York date +\\%H:\\%M)" = "{et_time}" ] &&'


def build(et_time: str, dow: str, command: str, comment: str) -> str:
    hours, et = SLOTS[et_time]
    return f"0 {hours} * * {dow} {guard(et)} {command}  # {comment}"


# Each rule: (regex matching the existing line, replacement builder)
# `held` preserves the #HOLD prefix — timing changes, hold state does not.
RULES = [
    # ── Daily -> 8:00 AM ET ────────────────────────────────────────────────
    (r"^0 21 \* \* \* /root/\.openclaw/agents/victoria/run_victoria\.sh\s*$",
     lambda m: build("08:00", "*", "/root/.openclaw/agents/victoria/run_victoria.sh",
                     "Victoria daily — 8:00 AM ET")),

    (r"^0 6 \* \* \*\s+cd /root/\.openclaw/agents/tao && python3 tao_subnet_scorer\.py.*$",
     lambda m: build("08:00", "*",
                     "cd /root/.openclaw/agents/tao && python3 tao_subnet_scorer.py >> tao.log 2>&1",
                     "Tao daily scorer — 8:00 AM ET")),

    # ── Daily briefing -> 8:00 PM ET, STAYS HELD ───────────────────────────
    (r"^#HOLD 0 7 \* \* \* python3 /root/\.openclaw/scripts/daily_briefing\.py.*$",
     lambda m: "#HOLD " + build("20:00", "*",
                     "python3 /root/.openclaw/scripts/daily_briefing.py >> /root/.openclaw/logs/daily_briefing.log 2>&1",
                     "daily briefing — 8:00 PM ET (HELD: timing only)")),

    # ── Weekly -> Sunday 8:00 AM ET ────────────────────────────────────────
    (r"^0 7 \* \* 1 /root/\.openclaw/agents/victoria/run_victoria_weekly\.sh\s*$",
     lambda m: build("08:00", "0", "/root/.openclaw/agents/victoria/run_victoria_weekly.sh",
                     "Victoria weekly — Sunday 8:00 AM ET")),

    (r"^0 10 \* \* 6 /root/\.openclaw/agents/norman/run_norman\.sh\s*$",
     lambda m: build("08:00", "0", "/root/.openclaw/agents/norman/run_norman.sh",
                     "Norman weekly — Sunday 8:00 AM ET")),

    (r"^0 21 \* \* 0 /root/\.openclaw/agents/lens/run_portfolio_thesis\.sh.*$",
     lambda m: build("08:00", "0",
                     "/root/.openclaw/agents/lens/run_portfolio_thesis.sh >> /root/.openclaw/logs/portfolio_thesis.log 2>&1",
                     "Lens portfolio thesis — Sunday 8:00 AM ET")),

    (r"^0 8 \* \* 6\s+cd /root/\.openclaw/agents/tao && python3 tao_compounder\.py.*$",
     lambda m: build("08:00", "0",
                     "cd /root/.openclaw/agents/tao && python3 tao_compounder.py >> tao.log 2>&1",
                     "Tao weekly compounder — Sunday 8:00 AM ET")),

    # Lucy: 0 12 * * 0 is 8 AM ET only while EDT is in force — in November it
    # silently becomes 7 AM EST. Same guard so it holds its slot year-round.
    (r"^0 12 \* \* 0 cd /root/\.openclaw/agents/lucy && python3 lucy_brain\.py --research.*$",
     lambda m: build("08:00", "0",
                     "cd /root/.openclaw/agents/lucy && python3 lucy_brain.py --research >> /root/.openclaw/logs/lucy.log 2>&1",
                     "Lucy weekly — Sunday 8:00 AM ET")),

    # ── Council -> Sunday 9:00 AM ET (1h after Lens, preserves the stagger) ─
    (r"^30 21 \* \* 0 /root/\.openclaw/scripts/run_council\.sh.*$",
     lambda m: build("09:00", "0",
                     "/root/.openclaw/scripts/run_council.sh >> /root/.openclaw/logs/council.log 2>&1",
                     "Council — Sunday 9:00 AM ET (1h after Lens thesis)")),
]

# Lines to drop entirely: the inert TZ block (misleading — implies the crontab
# has timezone-aware sections when this cron build ignores TZ for scheduling)
# and any leftover probe entries.
DROP = [
    r"^TZ=America/New_York\s*$",
    r"^TZ=UTC\s*$",
    r"^CRON_TZ=.*$",
    r".*cron_tz_test.*",
    r".*cron_guard_test.*",
]

HEADER = """# ─────────────────────────────────────────────────────────────────────────────
# TIMEZONE NOTE — read before editing
#
# This cron build (vixie-cron 3.0pl1, Ubuntu) schedules ONLY in system time,
# which is UTC. Neither `TZ=` nor `CRON_TZ=` changes when a job fires:
#   TZ=      -> sets the child process env only (man 5 crontab, LIMITATIONS)
#   CRON_TZ= -> a cronie feature; absent from this binary. Probe never fired.
#
# Jobs that must hold an America/New_York wall-clock time are therefore
# scheduled at BOTH candidate UTC hours with an ET guard:
#
#   0 12,13 * * *  [ "$(TZ=America/New_York date +\\%H:\\%M)" = "08:00" ] && cmd
#
# Exactly one candidate matches in each season, so DST needs no edit.
# Do not "simplify" these to a single UTC hour — that reintroduces the drift.
# ─────────────────────────────────────────────────────────────────────────────"""


def main(apply: bool):
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    out, changed, unmatched = [], [], {i for i in range(len(RULES))}

    for line in current.splitlines():
        if any(re.match(p, line) for p in DROP):
            changed.append(("DROP", line, ""))
            continue
        for i, (pattern, builder) in enumerate(RULES):
            if re.match(pattern, line):
                new = builder(re.match(pattern, line))
                changed.append(("EDIT", line, new))
                out.append(new)
                unmatched.discard(i)
                break
        else:
            out.append(line)

    out = HEADER.splitlines() + [""] + out

    print(f"=== {len(changed)} line(s) changed ===\n")
    for kind, old, new in changed:
        print(f"[{kind}]\n  - {old}")
        if new:
            print(f"  + {new}")
        print()

    if unmatched:
        print("!!! RULES THAT MATCHED NOTHING (schedule NOT applied):", file=sys.stderr)
        for i in sorted(unmatched):
            print(f"    rule[{i}]: {RULES[i][0]}", file=sys.stderr)
        print("Aborting — refusing to install a partial standardization.", file=sys.stderr)
        return 1

    if apply:
        subprocess.run(["crontab", "-"], input="\n".join(out) + "\n", text=True, check=True)
        print("✅ crontab installed")
    else:
        print("(dry run — pass --apply to install)")
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
