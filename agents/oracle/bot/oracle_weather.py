#!/usr/bin/env python3
"""oracle_weather.py — Weather for outdoor NFL/MLB games via Open-Meteo (free, no key)."""
import requests
from datetime import datetime, timezone

NFL_OUTDOOR = {
    'Buffalo Bills': (42.7738, -78.7870),
    'Chicago Bears': (41.8623, -87.6167),
    'Cincinnati Bengals': (39.0954, -84.5160),
    'Cleveland Browns': (41.5061, -81.6995),
    'Denver Broncos': (39.7439, -105.0201),
    'Green Bay Packers': (44.5013, -88.0622),
    'Kansas City Chiefs': (39.0489, -94.4839),
    'Miami Dolphins': (25.9580, -80.2389),
    'New England Patriots': (42.0909, -71.2643),
    'New York Giants': (40.8135, -74.0745),
    'New York Jets': (40.8135, -74.0745),
    'Philadelphia Eagles': (39.9008, -75.1675),
    'Pittsburgh Steelers': (40.4468, -80.0158),
    'San Francisco 49ers': (37.4033, -121.9694),
    'Seattle Seahawks': (47.5952, -122.3316),
    'Tennessee Titans': (36.1665, -86.7713),
    'Washington Commanders': (38.9078, -76.8644),
    'Carolina Panthers': (35.2258, -80.8528),
    'Jacksonville Jaguars': (30.3239, -81.6373),
    'Baltimore Ravens': (39.2780, -76.6227),
    'Detroit Lions': (42.3400, -83.0456),
}
MLB_OUTDOOR = {
    'Chicago Cubs': (41.9484, -87.6553),
    'Chicago White Sox': (41.8300, -87.6339),
    'Cincinnati Reds': (39.0979, -84.5070),
    'Cleveland Guardians': (41.4962, -81.6852),
    'Colorado Rockies': (39.7559, -104.9942),
    'Detroit Tigers': (42.3390, -83.0485),
    'Kansas City Royals': (39.0517, -94.4803),
    'Los Angeles Angels': (33.8003, -117.8827),
    'Los Angeles Dodgers': (34.0739, -118.2400),
    'Milwaukee Brewers': (43.0281, -87.9712),
    'New York Mets': (40.7571, -73.8458),
    'New York Yankees': (40.8296, -73.9262),
    'Philadelphia Phillies': (39.9061, -75.1665),
    'Pittsburgh Pirates': (40.4469, -80.0057),
    'San Diego Padres': (32.7076, -117.1570),
    'San Francisco Giants': (37.7786, -122.3893),
    'Seattle Mariners': (47.5914, -122.3325),
    'St. Louis Cardinals': (38.6226, -90.1928),
    'Texas Rangers': (32.7473, -97.0845),
    'Toronto Blue Jays': (43.6414, -79.3894),
    'Washington Nationals': (38.8730, -77.0074),
    'Baltimore Orioles': (39.2838, -76.6216),
    'Boston Red Sox': (42.3467, -71.0972),
    'Atlanta Braves': (33.8907, -84.4677),
}
VENUE_MAP = {**NFL_OUTDOOR, **MLB_OUTDOOR}

def get_game_weather(sport_label, away_team, home_team, commence_time):
    if sport_label not in ('NFL', 'MLB'):
        return None
    coords = VENUE_MAP.get(home_team)
    if not coords:
        return None
    lat, lon = coords
    try:
        game_time = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
    except Exception:
        return None
    date_str = game_time.strftime('%Y-%m-%d')
    try:
        r = requests.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude': lat, 'longitude': lon,
            'hourly': 'temperature_2m,precipitation_probability,wind_speed_10m',
            'temperature_unit': 'fahrenheit', 'wind_speed_unit': 'mph',
            'timezone': 'America/New_York',
            'start_date': date_str, 'end_date': date_str,
        }, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        hourly = data.get('hourly', {})
        times = hourly.get('time', [])
        temps = hourly.get('temperature_2m', [])
        winds = hourly.get('wind_speed_10m', [])
        precips = hourly.get('precipitation_probability', [])
        game_hour = game_time.hour
        target = f"{date_str}T{game_hour:02d}:00"
        idx = times.index(target) if target in times else min(game_hour, len(times)-1)
        temp = temps[idx] if idx < len(temps) else None
        wind = winds[idx] if idx < len(winds) else None
        precip = precips[idx] if idx < len(precips) else None
        flags = []
        if wind and wind >= 15:
            flags.append(f'💨 Wind {wind:.0f}mph — affects passing/kicking')
        if wind and wind >= 25:
            flags.append(f'🌬️ HIGH WIND {wind:.0f}mph — lean UNDER')
        if temp and temp <= 32:
            flags.append(f'🥶 Freezing ({temp:.0f}°F) — favors ground game')
        if precip and precip >= 50:
            flags.append(f'🌧️ Rain {precip}% — lean UNDER')
        return {'temp_f': temp, 'wind_mph': wind, 'precip_pct': precip, 'flags': flags, 'has_concerns': bool(flags)}
    except Exception as e:
        print(f'[weather] error for {home_team}: {e}')
        return None

if __name__ == '__main__':
    print('Weather module loaded OK')
