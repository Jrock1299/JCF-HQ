#!/usr/bin/env python3
"""
JCF HQ — Basketball Stats Scraper
Target: https://basketball.eurobasket.com/player/Jase-Febres/423908

Table 7  = Season summary  → Team, G, MIN, PTS, 2FGP, 3FGP, FT, RO, RD, RT, AS, PF, BS, ST, TO, RNK
Table 11 = Game log        → Date, Team, Against, Result, MIN, PTS, 2FGP, 3FGP, FT, RO, RD, RT, AS ...
"""
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone

URL    = "https://basketball.eurobasket.com/player/Jase-Febres/423908"
OUTPUT = "/root/.openclaw/dashboard/bball_stats.json"

headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

def safe(val):
    return val.strip() if val and val.strip() not in ('', '-', '**') else None

try:
    r    = requests.get(URL, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, 'html.parser')
    tables = soup.find_all("table")

    # ── TABLE 7: Season averages summary ──
    # Columns: Team | G | MIN | PTS | 2FGP | 3FGP | FT | RO | RD | RT | AS | PF | BS | ST | TO | RNK
    season = {}
    try:
        rows = tables[7].find_all("tr")
        # Row 1 = headers, Row 2 = totals data, Row 3 = "AVERAGES" label
        # Averages are in Table 8 (row 3) — PTS/G, 2FGM/G, 3FGM/G etc.
        # Use row 2 for totals, compute averages ourselves
        data_row = [td.get_text(strip=True) for td in rows[2].find_all(["td","th"])]
        # data_row: [Team, G, MIN, PTS, 2FGP, 3FGP, FT, RO, RD, RT, AS, PF, BS, ST, TO, RNK]
        team  = safe(data_row[0])
        games = int(data_row[1]) if data_row[1].isdigit() else 1

        def avg(val, g):
            try: return round(float(val) / g, 1)
            except: return None

        # Parse shooting splits like "51-87" → makes/attempts
        def split_pct(val):
            try:
                m, a = val.split('-')
                pct = round(int(m) / int(a) * 100, 1) if int(a) > 0 else 0
                return f"{m}/{a} ({pct}%)"
            except: return val

        season = {
            "team":       team,
            "games":      games,
            "ppg":        avg(data_row[3], games),
            "rpg":        avg(data_row[9], games),   # RT = total rebounds
            "apg":        avg(data_row[10], games),  # AS = assists
            "fg_pct":     split_pct(data_row[4]),    # 2FGP
            "tp_pct":     split_pct(data_row[5]),    # 3FGP
            "ft_pct":     split_pct(data_row[6]),    # FT
            "bpg":        avg(data_row[12], games),  # BS = blocks
            "spg":        avg(data_row[13], games),  # ST = steals
            "min_pg":     avg(data_row[2], games),   # MIN
        }
    except Exception as e:
        print(f"Season summary parse error: {e}")

    # ── TABLE 11: Game log ──
    # Columns: Date | Team | Against | Result | MIN | PTS | 2FGP | 3FGP | FT | RO | RD | RT | AS | PF | BS | ST | TO | RNK
    games_log = []
    try:
        rows = tables[11].find_all("tr")
        for row in rows[2:]:  # skip header rows
            cells = [td.get_text(strip=True) for td in row.find_all(["td","th"])]
            if len(cells) < 6:
                continue
            games_log.append({
                "date":    safe(cells[0]),
                "vs":      safe(cells[2]),
                "result":  safe(cells[3]),
                "min":     safe(cells[4]),
                "pts":     safe(cells[5]),
                "fg":      safe(cells[6]),
                "three":   safe(cells[7]),
                "ft":      safe(cells[8]),
                "reb":     safe(cells[11]),
                "ast":     safe(cells[12]),
            })
    except Exception as e:
        print(f"Game log parse error: {e}")

    output = {
        **season,
        "source":      URL,
        "scraped_at":  datetime.now(timezone.utc).isoformat(),
        "games_log":   games_log,
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Saved {OUTPUT}")
    # Print summary (not full game log)
    summary = {k: v for k, v in output.items() if k != 'games_log'}
    summary['games_log_count'] = len(games_log)
    print(json.dumps(summary, indent=2))

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback; traceback.print_exc()
    with open(OUTPUT, "w") as f:
        json.dump({"error": str(e), "scraped_at": datetime.now(timezone.utc).isoformat()}, f)
