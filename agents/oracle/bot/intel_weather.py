#!/usr/bin/env python3
"""
intel_weather.py — Layer 3: Weather edge for MLB outdoor games.
Uses Open-Meteo (free, no API key) + mlb_stadiums.json for field orientation.
Returns weather_edge: float (-1.0 to 1.0).
Positive = favors Over (hitter-friendly). Negative = favors Under (pitcher-friendly).
ONLY applies to MLB outdoor stadiums on totals and team totals.
"""
import json
import math
import requests
from datetime import datetime, timezone

STADIUMS_PATH = '/root/.openclaw/agents/oracle/bot/mlb_stadiums.json'

_stadiums_cache: dict | None = None


def _load_stadiums() -> dict:
    global _stadiums_cache
    if _stadiums_cache is not None:
        return _stadiums_cache
    try:
        with open(STADIUMS_PATH) as f:
            _stadiums_cache = json.load(f)
    except Exception as e:
        print(f'[intel_weather] could not load stadiums: {e}')
        _stadiums_cache = {}
    return _stadiums_cache


def get_weather_edge(sport: str, home_team: str, commence_time: str,
                     bet_type: str | None = None) -> float:
    """
    Returns weather_edge for an MLB outdoor game.

    Returns 0.0 for:
    - Non-MLB sports (NBA/NHL/NFL play indoors or weather not relevant here)
    - Dome / retractable-roof stadiums
    - Non-total bet types (ML/SPREAD weather impact is indirect; we only model totals)
    - Missing stadium data
    """
    if sport != 'MLB':
        return 0.0
    if bet_type and bet_type not in ('TOTAL', 'TEAM_TOTAL'):
        return 0.0

    stadiums = _load_stadiums()
    stadium = stadiums.get(home_team)
    if not stadium:
        return 0.0
    if stadium.get('dome', False):
        return 0.0  # Controlled environment — no weather edge

    lat = stadium['lat']
    lon = stadium['lon']
    orientation = stadium.get('orientation', 220)  # degrees: direction CF faces from HP

    try:
        game_time = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
    except Exception:
        return 0.0

    date_str = game_time.strftime('%Y-%m-%d')
    try:
        r = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude':           lat,
                'longitude':          lon,
                'hourly':             'temperature_2m,precipitation_probability,wind_speed_10m,wind_direction_10m',
                'temperature_unit':   'fahrenheit',
                'wind_speed_unit':    'mph',
                'timezone':           'America/New_York',
                'start_date':         date_str,
                'end_date':           date_str,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return 0.0
        data = r.json()
    except Exception as e:
        print(f'[intel_weather] API error for {home_team}: {e}')
        return 0.0

    hourly   = data.get('hourly', {})
    times    = hourly.get('time', [])
    temps    = hourly.get('temperature_2m', [])
    winds    = hourly.get('wind_speed_10m', [])
    wdirs    = hourly.get('wind_direction_10m', [])
    precips  = hourly.get('precipitation_probability', [])

    game_hour = game_time.hour
    target    = f"{date_str}T{game_hour:02d}:00"
    idx       = times.index(target) if target in times else min(game_hour, len(times) - 1)

    temp        = temps[idx]  if idx < len(temps)   else None
    wind_speed  = winds[idx]  if idx < len(winds)   else None
    wind_dir    = wdirs[idx]  if idx < len(wdirs)   else None
    precip      = precips[idx] if idx < len(precips) else None

    edge = 0.0

    # ── Wind component ────────────────────────────────────────────────────────
    if wind_speed and wind_dir is not None and wind_speed >= 8:
        # wind_dir = where wind comes FROM (meteorological convention)
        # Wind blows TOWARD (wind_dir + 180) % 360
        wind_toward = (wind_dir + 180) % 360

        # Angle between wind direction and CF direction
        angle_diff = abs(wind_toward - orientation) % 360
        if angle_diff > 180:
            angle_diff = 360 - angle_diff

        # cos(0) =  1.0 → wind blowing straight out to CF (hitter-friendly)
        # cos(180) = -1.0 → wind blowing straight in from CF (pitcher-friendly)
        wind_out_factor = math.cos(math.radians(angle_diff))

        # Scale by speed: 10mph = 0.5 strength, 20mph = full strength
        speed_factor = min(wind_speed / 20.0, 1.0)
        wind_contribution = wind_out_factor * speed_factor * 0.8
        edge += wind_contribution

    # ── Temperature component ─────────────────────────────────────────────────
    if temp is not None:
        if temp < 50:
            # Cold air suppresses ball carry + reduces offense
            cold_factor = min((50 - temp) / 30.0, 1.0)  # maxes out at 20°F
            edge -= cold_factor * 0.4
        elif temp > 88:
            # Hot weather — ball carries slightly better
            hot_factor = min((temp - 88) / 12.0, 1.0)
            edge += hot_factor * 0.15

    # ── Precipitation component ───────────────────────────────────────────────
    if precip and precip >= 50:
        rain_factor = min((precip - 50) / 50.0, 1.0)
        edge -= rain_factor * 0.5

    return round(max(-1.0, min(1.0, edge)), 3)


if __name__ == '__main__':
    # Quick smoke test
    e = get_weather_edge('MLB', 'Chicago Cubs', '2026-04-01T18:05:00Z', 'TOTAL')
    print(f'Wrigley weather edge: {e}')
    e2 = get_weather_edge('NBA', 'Boston Celtics', '2026-04-01T19:30:00Z', 'TOTAL')
    print(f'NBA (should be 0.0): {e2}')
