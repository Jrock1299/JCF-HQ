#!/usr/bin/env python3
import os, json, re, datetime, sys
from firecrawl import V1FirecrawlApp
def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass

load_env()

OUT_PATH = "/root/.openclaw/dashboard/bball_stats.json"
URL = "https://basketball.eurobasket.com/player/Jase-Febres/423908"

API_KEY = os.getenv("FIRECRAWL_API_KEY")
if not API_KEY:
    print("Missing FIRECRAWL_API_KEY in /etc/environment", file=sys.stderr)
    sys.exit(1)

app = V1FirecrawlApp(api_key=API_KEY)

# scrape page
res = app.scrape_url(URL, formats=["markdown","html"])
res_dict = res.model_dump() if hasattr(res, 'model_dump') else (res.__dict__ if hasattr(res,'__dict__') else {})
md = res_dict.get('markdown','') or ''
html = res_dict.get('html','') or ''
text = md + "\n" + re.sub('<[^<]+?>',' ', html)

# helpers

def find_stat(patterns):
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return 0.0

# parse AVERAGES row for Ploiesti CSM
ppg=rpg=apg=fgp=threep=0.0
games_played=0
team="Ploiesti CSM"

avg_row=None
seen_avg=False
for line in md.splitlines():
    if 'AVERAGES' in line:
        seen_avg=True
        continue
    if seen_avg and line.strip().startswith('| Ploiesti CSM |'):
        avg_row=line
        break
if avg_row:
    cols=[c.strip() for c in avg_row.strip().strip('|').split('|')]
    # columns: Team, G, MIN, PTS, 2FGP, 3FGP, FT, RO, RD, RT, AS, PF, BS, ST, TO, RNK
    try:
        games_played=int(cols[1])
        ppg=float(cols[3])
        fgp=float(cols[4].replace('%',''))
        threep=float(cols[5].replace('%',''))
        rpg=float(cols[9])
        apg=float(cols[10])
    except Exception:
        pass

# wins/losses not on player page (manual)
wins=6
losses=13

# jersey number (manual)
number = "13"

out = {
    "ppg": ppg,
    "rpg": rpg,
    "apg": apg,
    "fgp": fgp,
    "threep": threep,
    "team": team,
    "wins": wins,
    "losses": losses,
    "games_played": games_played,
    "number": number,
    "last_update": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
}

with open(OUT_PATH, 'w') as f:
    json.dump(out, f, indent=2)

print(f"Saved {OUT_PATH}")
