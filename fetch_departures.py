#!/usr/bin/env python3

"""Simple script to fetch and print the next Swiss public transport departures.

Format per line:
  line destination minutes_until_departure

Usage:
  python fetch_departures.py

Adjust STOP, LIMIT, and TRANSPORTS constants below as desired.
"""
from __future__ import annotations

import sys
import argparse
import re
import unicodedata
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

import os
import requests


API_URL = "https://transport.opendata.ch/v1/stationboard"

# Predefined stop (can be station or stop name). Examples:
#   "Zürich, Central" (tram hub) or "Zürich HB" (main station)
STOP = "Basel, Aeschenplatz"

# Optional predefined destination filter. Set to a station name (e.g. "Zürich HB")
# to only show direct departures ending there. Leave as None to show all.
DESTINATION_FILTER: Optional[str] = None

# Number of departures to fetch
LIMIT = 4

# Restrict to certain transport types (API expects repeated key transportations[])
# Examples: ["tram"], ["bus"], ["train"], ["tram", "train"]. Set to None for all.
TRANSPORTS: Optional[List[str]] = ["tram", "train"]


def _default_ca_bundle() -> str | None:
    """Return a usable CA bundle path if certifi path is broken.

    Tries:
      1. certifi.where()
      2. /etc/ssl/certs/ca-certificates.crt (Debian/RPi OS default)
    Returns None if neither exists (requests will then raise).
    """
    try:
        import certifi  # type: ignore
        path = certifi.where()
        if os.path.exists(path):
            return path
    except Exception:  # noqa: BLE001
        pass
    fallback = "/etc/ssl/certs/ca-certificates.crt"
    if os.path.exists(fallback):
        return fallback
    return None


def fetch_stationboard(
    station: str,
    limit: int = 8,
    transportations: Optional[List[str]] = None,
    timeout: float | Tuple[float, float] = 10.0,
    verify: bool | str = True,
) -> List[Dict[str, Any]]:
    """Return a simplified list of upcoming departures for a station.

    Each row dict contains: line, dest, mins, delay, plat.
    Logic details:
      - Over-fetch from the API (limit + buffer) so after filtering out imminent
        departures (<3 mins) we can still present the desired number of rows.
      - Rows with mins < 3 are excluded.
    timeout can be a single float (seconds) or a (connect, read) tuple forwarded
    to requests.get for finer control during boot.
    """
    display_limit = limit
    fetch_buffer = max(10, int(display_limit * 2))
    fetch_limit = display_limit + fetch_buffer
    params: Dict[str, Any] = {"station": station, "limit": fetch_limit}
    if transportations:
        params["transportations[]"] = transportations

    # Decide verification behavior
    if verify is True:
        # Attempt to ensure a valid CA bundle even if certifi path is missing
        ca = _default_ca_bundle()
        verify_param: bool | str = ca if ca else True
    else:  # verify explicitly False or custom path string
        verify_param = verify if verify is not None else True
    r = requests.get(API_URL, params=params, timeout=timeout, verify=verify_param)
    r.raise_for_status()
    data = r.json()
    rows: List[Dict[str, Any]] = []
    for j in data.get("stationboard", []):
        stop = j.get("stop", {}) or {}
        when = (stop.get("prognosis") or {}).get("departure") or stop.get("departure")
        if not when:
            continue
        when = when.replace("Z", "+00:00")
        try:
            dep = datetime.fromisoformat(when)
        except ValueError:
            continue
        now = datetime.now(dep.tzinfo)
        mins = max(0, int((dep - now).total_seconds() // 60))
        delay = stop.get("delay") or 0
        category = (j.get("category") or "").strip()
        number = (j.get("number") or "").strip()
        line = f"{category}{number}".strip()
        dest = j.get("to") or ""
        plat = stop.get("platform") or ""
        rows.append({
            "line": line,
            "category": category,
            "number": number,
            "dest": dest,
            "mins": mins,
            "delay": delay,
            "plat": plat,
        })
    rows = [r for r in rows if r["mins"] >= 3]
    # Sort by planned + delay (requirement: order by sum of planned + delay)
    rows.sort(key=lambda r: (r.get("mins", 0) + (r.get("delay") or 0)))
    return rows


def _station_city(station_name: str) -> str:
    """Extract city part (text before first comma) from a station name."""
    if "," in station_name:
        return station_name.split(",", 1)[0].strip()
    return station_name.strip()


def _strip_same_city(dest: str, station_city: str) -> str:
    """Remove leading '<city>, ' from destination if same city.

    Extended to be accent/diacritic-insensitive: 'Zürich, Central' will
    match station city 'Zurich' or 'Zürich'. We normalize both sides by
    decomposing Unicode characters and stripping combining marks before
    lowercasing for comparison. The original (unmodified) destination
    substring after the comma is returned to preserve accents.
    """
    d = dest.strip()
    sc = station_city.strip()
    if not sc or "," not in d:
        return d
    city_part, remainder = d.split(",", 1)

    def _fold(s: str) -> str:
        # Normalize to NFKD then remove combining marks (category 'Mn')
        nk = unicodedata.normalize("NFKD", s)
        return "".join(ch for ch in nk if unicodedata.category(ch) != "Mn").lower().strip()

    if _fold(city_part) == _fold(sc):
        return remainder.strip()
    return d


BAHNHOF_PATTERN = re.compile(r"bahnhof", re.IGNORECASE)
STRASSE_PATTERN = re.compile(r"strasse", re.IGNORECASE)



def format_departure(row: Dict[str, Any], station_name: str = STOP) -> str:
    """Format a single departure line:

    - Tram: show just the numeric part (no 'T')
    - Train/other: show category+number
    - Destination: strip city if same as station's city
    - Minutes: single integer minutes until (no delay suffix)
    """
    category = (row.get("category") or "").strip()
    number = (row.get("number") or "").strip()
    if category.upper() in {"T", "TRAM"} and number:
        line = number  # tram => just number
    else:
        # Keep original combined line (already built) if present, else fallback to category/number
        line = row.get("line") or f"{category}{number}" or "?"

    station_city = _station_city(station_name)
    dest_raw = (row.get("dest") or "").replace("\n", " ")
    dest = _strip_same_city(dest_raw, station_city)
    # Abbreviate 'Bahnhof' -> 'Bhf.'
    dest = BAHNHOF_PATTERN.sub("Bhf.", dest)
    dest = STRASSE_PATTERN.sub("Str.", dest)

    mins = row.get("mins", 0)
    return f"{line} {dest} {mins}'".strip()


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Swiss public transport departures.")
    parser.add_argument("origin", nargs="?", default=STOP, help="Origin station name (default: %(default)s)")
    parser.add_argument(
        "destination",
        nargs="?",
    default=DESTINATION_FILTER,
        help="Optional destination station to filter direct train departures.")
    parser.add_argument("--limit", type=int, default=LIMIT, help="Number of departures to fetch (default: %(default)s)")
    parser.add_argument("--all", action="store_true", help="Include all transport types (override default tram/train filter).")
    args = parser.parse_args(argv)

    origin = args.origin
    dest_filter = args.destination
    transports = None if args.all else TRANSPORTS

    try:
        if dest_filter:
            # Progressive enlargement strategy to find enough direct trains:
            needed = args.limit
            nf = _normalize(dest_filter)
            fetch_size = max(needed * 6, 60)  # start fairly large for busy hubs
            max_fetch = 240  # hard ceiling to avoid excessive API load
            filtered: List[Dict[str, Any]] = []
            attempt = fetch_size
            while attempt <= max_fetch and len(filtered) < needed:
                broad_rows = fetch_stationboard(origin, attempt, transports)
                # Filter trains only (exclude trams) and exact destination match
                filtered = [
                    r for r in broad_rows
                    if (r.get("category") or "").upper() not in {"T", "TRAM"}
                    and _normalize(r.get("dest") or "") == nf
                ]
                if len(filtered) >= needed:
                    break
                # Increase attempt size (add another large chunk)
                attempt += max(needed * 4, 40)
            rows = filtered[:needed]
        else:
            rows_all = fetch_stationboard(origin, args.limit, transports)
            rows = rows_all[: args.limit]
    except requests.RequestException as e:
        print(f"Error fetching departures: {e}", file=sys.stderr)
        return 1

    if not rows:
        if dest_filter:
            print(f"No direct departures from '{origin}' to '{dest_filter}'.")
        else:
            print("No departures found.")
        return 0
    for row in rows:
        print(format_departure(row, origin))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
