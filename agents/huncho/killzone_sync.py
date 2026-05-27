#!/usr/bin/env python3
"""
Huncho — Kill Zone Sync

Given a city name, compute local times for London/NY/Asia kill zones and schedule
Telegram pings 15 minutes before each. The city/timezone is saved to a config
file so it persists until Jase updates it.

Usage (from Huncho or shell):
    python3 killzone_sync.py deploy "London"
    python3 killzone_sync.py show
    python3 killzone_sync.py run asia    # manually fire the alert

Kill zones (UTC):
    Asia:   00:00 open (alert 23:45 prior day)
    London: 06:00 open (alert 05:45)
    NY:     13:30 open (alert 13:15)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONFIG_PATH  = Path("/root/.openclaw/agents/huncho/killzone_config.json")
CRON_MARKER  = "# HUNCHO_KILLZONE"
TELEGRAM_UID = "797062420"
LOG_PATH     = Path("/root/.openclaw/agents/huncho/huncho.log")

# Kill zone opens in UTC
KILL_ZONES = {
    "Asia":   time(hour=0,  minute=0),   # 00:00 UTC
    "London": time(hour=6,  minute=0),   # 06:00 UTC
    "NY":     time(hour=13, minute=30),  # 13:30 UTC
}
ALERT_LEAD = timedelta(minutes=15)

# Simple city → IANA timezone map. Extend by dropping names into TZ_ALIASES.
TZ_ALIASES = {
    "new york":    "America/New_York",
    "nyc":         "America/New_York",
    "los angeles": "America/Los_Angeles",
    "la":          "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "chicago":     "America/Chicago",
    "denver":      "America/Denver",
    "miami":       "America/New_York",
    "london":      "Europe/London",
    "paris":       "Europe/Paris",
    "berlin":      "Europe/Berlin",
    "madrid":      "Europe/Madrid",
    "rome":        "Europe/Rome",
    "amsterdam":   "Europe/Amsterdam",
    "dubai":       "Asia/Dubai",
    "tokyo":       "Asia/Tokyo",
    "singapore":   "Asia/Singapore",
    "hong kong":   "Asia/Hong_Kong",
    "sydney":      "Australia/Sydney",
    "melbourne":   "Australia/Melbourne",
    "toronto":     "America/Toronto",
    "mexico city": "America/Mexico_City",
    "sao paulo":   "America/Sao_Paulo",
    "bali":        "Asia/Makassar",
    "bangkok":     "Asia/Bangkok",
    "seoul":       "Asia/Seoul",
    "mumbai":      "Asia/Kolkata",
    "lisbon":      "Europe/Lisbon",
    "zurich":      "Europe/Zurich",
}

def log(msg):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with LOG_PATH.open("a") as f:
        f.write(f"[{stamp}] {msg}\n")
    print(msg)

def resolve_timezone(city):
    """Return an IANA tz string for a city name, or None if unknown."""
    key = city.strip().lower()
    if key in TZ_ALIASES:
        return TZ_ALIASES[key]
    # Also accept a raw IANA name (e.g. "Europe/Madrid")
    try:
        ZoneInfo(city)
        return city
    except (ZoneInfoNotFoundError, ValueError):
        return None

def send_telegram(msg):
    try:
        subprocess.run([
            "openclaw", "message", "send",
            "--channel", "telegram", "--target", TELEGRAM_UID, "--message", msg
        ], timeout=15)
    except Exception as e:
        log(f"telegram send failed: {e}")

def local_times_for(tz_name):
    """Return {zone: (local_open_str, local_alert_str)} for a given IANA tz."""
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    result = {}
    for zone, t_utc in KILL_ZONES.items():
        dt_utc    = datetime.combine(today, t_utc, tzinfo=timezone.utc)
        dt_local  = dt_utc.astimezone(tz)
        alert_loc = dt_local - ALERT_LEAD
        result[zone] = (dt_local.strftime("%H:%M"), alert_loc.strftime("%H:%M"))
    return result

def write_crontab(tz_name):
    """Replace any HUNCHO_KILLZONE lines in crontab with fresh alert schedule.
    Alerts fire 15 min before each zone open. Cron expressions are in the
    server's timezone (configured via TZ= lines in the crontab)."""
    # Build one cron line per zone. Fires 15min before UTC open.
    # Cron server runs on UTC (per existing crontab TZ=UTC directive).
    cron_lines = []
    for zone, t_utc in KILL_ZONES.items():
        open_dt   = datetime.combine(datetime.utcnow().date(), t_utc, tzinfo=timezone.utc)
        alert_dt  = open_dt - ALERT_LEAD
        cron_h    = alert_dt.hour
        cron_m    = alert_dt.minute
        cmd = (f"{cron_m} {cron_h} * * * python3 /root/.openclaw/agents/huncho/killzone_sync.py "
               f"run {zone.lower()} >> /root/.openclaw/agents/huncho/huncho.log 2>&1  {CRON_MARKER}")
        cron_lines.append(cmd)

    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    kept = [ln for ln in current.splitlines() if CRON_MARKER not in ln]
    new  = "\n".join(kept + cron_lines) + "\n"
    proc = subprocess.run(["crontab", "-"], input=new, text=True, capture_output=True)
    if proc.returncode != 0:
        log(f"crontab install failed: {proc.stderr}")
        return False
    log(f"crontab updated — {len(cron_lines)} kill zone alerts for {tz_name}")
    return True

def save_config(city, tz_name):
    data = {
        "city":    city,
        "timezone": tz_name,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))

def load_config():
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return None

def deploy(city_arg):
    """Configure kill-zone alerts for the given city."""
    tz_name = resolve_timezone(city_arg)
    if not tz_name:
        msg = (f"❓ Unknown city: {city_arg}\n"
               f"Add it to TZ_ALIASES in killzone_sync.py or use an IANA timezone "
               f"(e.g. 'Europe/Madrid').")
        send_telegram(msg); print(msg)
        return 1

    save_config(city_arg, tz_name)
    write_crontab(tz_name)

    times = local_times_for(tz_name)
    city_label = city_arg.title()
    lines = [f"✅ Kill Zones synced for {city_label} ({tz_name})"]
    for zone in ("Asia", "London", "NY"):
        open_local, alert_local = times[zone]
        lines.append(f"  {zone}: {open_local} local — alert at {alert_local}")
    msg = "\n".join(lines)
    send_telegram(msg)
    log(msg)
    return 0

def show():
    cfg = load_config()
    if not cfg:
        msg = "No kill zone config found. Run: killzone_sync.py deploy <city>"
        print(msg); return 1
    times = local_times_for(cfg["timezone"])
    print(f"Current kill zone sync: {cfg['city']} ({cfg['timezone']})")
    for zone, (open_local, alert_local) in times.items():
        print(f"  {zone}: {open_local} local — alert at {alert_local}")
    return 0

def run_alert(zone_key):
    """Called by cron — fires the 15-min-prior ping."""
    zone_map = {z.lower(): z for z in KILL_ZONES}
    zone = zone_map.get(zone_key.lower())
    if not zone:
        log(f"run_alert: unknown zone '{zone_key}'")
        return 1
    cfg = load_config()
    if not cfg:
        log("run_alert: no kill zone config set"); return 1
    tz_name = cfg["timezone"]
    times   = local_times_for(tz_name)
    open_local, _ = times[zone]
    msg = f"⚡ KILL ZONE in 15 min — {zone} opens at {open_local} ({tz_name})"
    send_telegram(msg)
    log(f"alert sent: {zone}")
    return 0

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "deploy":
        if len(sys.argv) < 3:
            print("Usage: killzone_sync.py deploy <city>"); sys.exit(1)
        sys.exit(deploy(" ".join(sys.argv[2:])))
    elif cmd == "show":
        sys.exit(show())
    elif cmd == "run":
        if len(sys.argv) < 3:
            print("Usage: killzone_sync.py run <asia|london|ny>"); sys.exit(1)
        sys.exit(run_alert(sys.argv[2]))
    else:
        print(__doc__); sys.exit(1)

if __name__ == "__main__":
    main()
