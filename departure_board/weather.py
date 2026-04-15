"""Weather integration using Open-Meteo (no API key needed)."""
from __future__ import annotations

from typing import Any, Dict, List

import requests


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
        f'&timezone={tz}'
    )
    # Split timeouts similar to departures
    connect_timeout = min(1.0, max(0.2, timeout / 3.0))
    read_timeout = max(2.5, timeout)
    r = requests.get(url, timeout=(connect_timeout, read_timeout))
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
    )
    return out
