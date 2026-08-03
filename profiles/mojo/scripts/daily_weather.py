#!/usr/bin/env python3
"""
Daily weather report for the configured Mojo location.
Data source: Open-Meteo (free, no API key required).
"""

import os
import urllib.request
import urllib.error
import json
import sys
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
LAT = float(os.environ["MOJO_WEATHER_LAT"])
LON = float(os.environ["MOJO_WEATHER_LON"])
CITY = os.environ["MOJO_WEATHER_CITY"]

URL = (
    f"https://api.open-meteo.com/v1/forecast?"
    f"latitude={LAT}&longitude={LON}"
    f"&daily=temperature_2m_max,temperature_2m_min,apparent_temperature_max,"
    f"apparent_temperature_min,precipitation_sum,precipitation_probability_max,"
    f"weathercode"
    f"&hourly=temperature_2m,precipitation_probability,precipitation,weathercode"
    f"&current_weather=true"
    f"&timezone=America/Argentina/Buenos_Aires"
    f"&forecast_days=1"
)

WEATHER_ICONS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌧️", 53: "🌧️", 55: "🌧️", 56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌧️", 81: "🌧️", 82: "🌧️",
    85: "❄️", 86: "❄️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

BLOCKS = [
    ("Mañana", 6, 12),
    ("Tarde", 12, 18),
    ("Noche", 18, 24),
]


def fetch_weather():
    """Fetch weather from Open-Meteo with retry."""
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "hermes-weather/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            if e.code < 500:
                break
        except urllib.error.URLError as e:
            last_error = f"URLError: {e.reason}"
        except OSError as e:
            last_error = f"OSError: {e}"
        if attempt < 2:
            _time.sleep(2 ** attempt)

    raise RuntimeError(f"Open-Meteo no disponible tras 3 intentos: {last_error}")


def render():
    data = fetch_weather()
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    hourly = data["hourly"]

    today_hours = []
    for k, t in enumerate(hourly["time"]):
        if not t.startswith(today):
            continue
        hour = int(t.split("T")[1].split(":")[0])
        today_hours.append({
            "hour": hour,
            "temp": hourly["temperature_2m"][k],
            "prob": hourly["precipitation_probability"][k],
            "code": hourly["weathercode"][k],
        })

    day = now.day
    month = MESES[now.month - 1]
    lines = [f"📅 Reporte para el {day} de {month} en {CITY}:"]

    for label, start, end in BLOCKS:
        block = [h for h in today_hours if start <= h["hour"] < end]
        if not block:
            continue
        tmin = min(h["temp"] for h in block)
        tmax = max(h["temp"] for h in block)
        max_prob = max(h["prob"] for h in block)
        worst = max(block, key=lambda h: (h["prob"], h["code"]))
        emoji = WEATHER_ICONS.get(worst["code"], "🌡️")
        lines.append(
            f"{emoji} {label}: {round(tmin)}°C - {round(tmax)}°C | Lluvia: {round(max_prob)}%"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        print(render())
    except Exception as e:
        print(f"❌ No se pudo obtener el clima: {e}", file=sys.stderr)
        sys.exit(1)
