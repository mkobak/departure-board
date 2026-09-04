"""Weather integration using Open-Meteo (no API key needed)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

# Precipitation summary line ("Rain from 13:45" etc.) --------------------------
# A 15-minute slot counts as wet when ALL of these hold:
#  - the slot itself has at least PRECIP_THRESHOLD_MM (0.1 mm is the model's smallest value),
#  - the hour starting at that slot totals at least PRECIP_HOUR_MIN_MM (filters isolated
#    0.1 mm traces and all-day drizzle that other services report as "no rain"; light
#    rain of ~0.5 mm/h and up still passes),
#  - the model's precipitation probability for the slot is at least PRECIP_MIN_PROBABILITY
#    percent (skipped when the API returns no probability).
PRECIP_THRESHOLD_MM = 0.1
PRECIP_HOUR_MIN_MM = 0.3
PRECIP_MIN_PROBABILITY = 35
# From this hour on the summary looks at tomorrow instead of the rest of today.
PRECIP_EVENING_HOUR = 20

_SESSION: Optional["requests.Session"] = None


def _session() -> "requests.Session":
    """Shared keep-alive session (skips TLS handshake on repeat fetches)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


class WeatherData(Dict[str, Any]):
    pass


WEATHER_CITIES = [
    {
        'city': 'Basel',
        'lat': 47.5596,
        'lon': 7.5886,
        'header': 'Basel',
    },
    {
        'city': 'Z\u00fcrich',
        'lat': 47.3769,
        'lon': 8.5417,
        'header': 'Z\u00fcrich',
    },
]


def _w_code_to_kind_desc(code: int) -> Dict[str, str]:
    """Map Open-Meteo weather_code to a coarse kind and description.
    Kinds: sunny, partly, cloudy, fog, rain, snow, thunder
    """
    # Ref: https://open-meteo.com/en/docs
    if code in (0,):
        return {'kind': 'sunny', 'desc': 'Sonnig'}
    if code in (1, 2):
        return {'kind': 'partly', 'desc': 'Wolkig'}
    if code in (3,):
        return {'kind': 'cloudy', 'desc': 'Bedeckt'}
    if code in (45, 48):
        return {'kind': 'fog', 'desc': 'Nebel'}
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return {'kind': 'rain', 'desc': 'Regen'}
    if code in (71, 73, 75, 77, 85, 86):
        return {'kind': 'snow', 'desc': 'Schnee'}
    if code in (95, 96, 99):
        return {'kind': 'thunder', 'desc': 'Gewitter'}
    return {'kind': 'cloudy', 'desc': 'Wetter'}


# Predefined 15x15 pixel icons (1 = lit, 0 = dark). Easy to edit.
# Keys should match values from _w_code_to_kind_desc.kind
ICON_SIZE = 15
WEATHER_ICONS: Dict[str, List[str]] = {
    'sunny': ["000000000000000","000000010000000","001000010000100","000100000001000","000000111000000","000001000100000","000010000010000","011010000010110","000010000010000","000001000100000","000000111000000","000100000001000","001000010000100","000000010000000","000000000000000"],
    'partly': ["000000000000000","000000010000000","001000010000100","000100000001000","000000111000000","000001000100000","000010000010000","011010000111000","000010011000100","000001100001110","000001000010001","000101000000001","001000100000001","000000011111110","000000000000000"],
    'cloudy': ["000000000000000","000000000000000","000001110000000","000010001100000","001100000010000","010000000111000","100000011000100","100001100001110","100010000010001","010010000010001","001110000000001","000010000000010","000001111111100","000000000000000","000000000000000"],
    'fog': ["000000000000000","000000000000000","000000000000000","000011111111110","000000000000000","011111111111000","000000000000000","000111111111111","000000000000000","111111111110000","000000000000000","001111111111100","000000000000000","000000000000000","000000000000000"],
    'rain': ["000001110000000","000010001100000","001100000010000","010000000111000","100000011000100","100001100001110","100010000010001","010010000010001","001110000000001","000010000000010","000001111111100","000000000000000","000100100100100","001001001001000","010010010010000"],
    'snow': ["000001110000000","000010001100000","001100000010000","010000000111000","100000011000100","100001100001110","100010000010001","010010000010001","001110000000001","000010000000010","010001111111100","000000000000000","000100010000100","100000000100000","000001000000010"],
    'thunder': ["000001110000000","000010001100000","001100000010000","010000000111000","100000011000110","100001100001001","010010000000001","001110000000001","000010000100010","000001101011100","000000010000000","000000111110000","000000000100000","000000001000000","000000010000000"],
}


def fetch_weather(lat: float, lon: float, timeout: float = 6.0) -> WeatherData:
    tz = 'Europe/Zurich'
    url = (
        'https://api.open-meteo.com/v1/forecast'
        f'?latitude={lat}&longitude={lon}'
        '&current=temperature_2m,weather_code,relative_humidity_2m,apparent_temperature,wind_speed_10m'
        '&daily=temperature_2m_max,temperature_2m_min,uv_index_max,precipitation_probability_max'
        # 15-minute precipitation for today and tomorrow (192 slots, ~7 KB)
        '&minutely_15=precipitation,snowfall,precipitation_probability&forecast_days=2'
        f'&timezone={tz}'
    )
    # Split timeouts similar to departures
    connect_timeout = min(1.0, max(0.2, timeout / 3.0))
    read_timeout = max(2.5, timeout)
    r = _session().get(url, timeout=(connect_timeout, read_timeout))
    r.raise_for_status()
    j = r.json()
    cur = j.get('current', {}) or j.get('current_weather', {})
    daily = j.get('daily', {})
    # Some variants use 'current_weather'; normalize keys
    temp_now = cur.get('temperature_2m') if 'temperature_2m' in cur else cur.get('temperature')
    wcode = int(cur.get('weather_code') if 'weather_code' in cur else cur.get('weathercode', 0) or 0)
    kind_desc = _w_code_to_kind_desc(wcode)
    tmin_list = list(daily.get('temperature_2m_min') or []) if daily else []
    tmax_list = list(daily.get('temperature_2m_max') or []) if daily else []
    pprob_list = list(daily.get('precipitation_probability_max') or []) if daily else []
    uvmax_list = list(daily.get('uv_index_max') or []) if daily else []
    tmin0 = tmin_list[0] if tmin_list else None
    tmax0 = tmax_list[0] if tmax_list else None
    pprob0 = pprob_list[0] if pprob_list else None
    uvmax0 = uvmax_list[0] if uvmax_list else None
    slots = _parse_minutely(j.get('minutely_15') or {})
    out: WeatherData = WeatherData(
        now_temp=round(float(temp_now)) if temp_now is not None else None,
        app_temp=round(float(cur.get('apparent_temperature'))) if cur.get('apparent_temperature') is not None else None,
        rh=int(cur.get('relative_humidity_2m')) if cur.get('relative_humidity_2m') is not None else None,
        wind=round(float(cur.get('wind_speed_10m'))) if cur.get('wind_speed_10m') is not None else None,
        code=wcode,
        kind=kind_desc['kind'],
        desc=kind_desc['desc'],
        tmin=round(float(tmin0)) if tmin0 is not None else None,
        tmax=round(float(tmax0)) if tmax0 is not None else None,
        pprob=int(round(float(pprob0))) if pprob0 is not None else None,
        uvmax=int(round(float(uvmax0))) if uvmax0 is not None else None,
        slots=slots,
    )
    return out


# (slot start time in local time, precipitation mm, snowfall cm, probability % or None)
PrecipSlot = Tuple[datetime, float, float, Optional[float]]


def _parse_minutely(m: Dict[str, Any]) -> List[PrecipSlot]:
    """Turn the Open-Meteo minutely_15 block into a list of PrecipSlot."""
    times = m.get('time') or []
    precip = m.get('precipitation') or []
    snow = m.get('snowfall') or []
    prob = m.get('precipitation_probability') or []
    out: List[PrecipSlot] = []
    for i, t in enumerate(times):
        try:
            ts = datetime.fromisoformat(t)
        except (TypeError, ValueError):
            continue
        p = precip[i] if i < len(precip) else None
        sn = snow[i] if i < len(snow) else None
        pr = prob[i] if i < len(prob) else None
        out.append((ts, float(p or 0.0), float(sn or 0.0), float(pr) if pr is not None else None))
    return out


def _wet_flags(slots: List[PrecipSlot]) -> List[bool]:
    """Per-slot 'wet' decision using the amount, hour-total and probability rules."""
    n = len(slots)
    flags: List[bool] = []
    for i, s in enumerate(slots):
        if s[1] < PRECIP_THRESHOLD_MM:
            flags.append(False)
            continue
        prob = s[3] if len(s) > 3 else None
        if prob is not None and prob < PRECIP_MIN_PROBABILITY:
            flags.append(False)
            continue
        hour_total = sum(slots[j][1] for j in range(i, min(n, i + 4)))
        flags.append(hour_total >= PRECIP_HOUR_MIN_MM)
    return flags


def precip_summary(slots: Optional[List[PrecipSlot]], now: Optional[datetime] = None) -> Optional[str]:
    """One-line precipitation outlook for the bottom of the weather screen.

    Before PRECIP_EVENING_HOUR the window is the rest of today, afterwards it is
    the rest of tonight plus all of tomorrow. Possible results:
      "Rain until 14:30"      raining now, first dry slot at 14:30
      "Rain now"              raining now with no dry slot in the window
      "Rain from 13:45"       dry now, first wet slot at 13:45 (still today)
      "Rain tomorrow 13:45"   evening mode, first wet slot is tomorrow
      "No rain today" / "No rain tomorrow"
    "Snow" replaces "Rain" when the slot reports snowfall. None if no data.
    """
    if not slots:
        return None
    now = now or datetime.now()
    evening = now.hour >= PRECIP_EVENING_HOUR
    today = now.date()
    horizon_day = today + timedelta(days=1) if evening else today
    flags = _wet_flags(slots)
    wet_by_time = {s[0]: f for s, f in zip(slots, flags)}
    window = [s for s in slots
              if s[0] + timedelta(minutes=15) > now and s[0].date() <= horizon_day]
    if not window:
        return None

    def wet(s: PrecipSlot) -> bool:
        return wet_by_time.get(s[0], False)

    def kind(s: PrecipSlot) -> str:
        return 'Snow' if s[2] > 0 else 'Rain'

    def hhmm(s: PrecipSlot) -> str:
        return s[0].strftime('%H:%M')

    first = window[0]
    if wet(first):
        dry = next((s for s in window[1:] if not wet(s)), None)
        return f"{kind(first)} until {hhmm(dry)}" if dry else f"{kind(first)} now"
    wet_slot = next((s for s in window if wet(s)), None)
    if wet_slot is None:
        return "No rain tomorrow" if evening else "No rain today"
    if wet_slot[0].date() != today:
        return f"{kind(wet_slot)} tomorrow {hhmm(wet_slot)}"
    return f"{kind(wet_slot)} from {hhmm(wet_slot)}"
