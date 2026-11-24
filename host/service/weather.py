"""Outdoor weather from Open-Meteo (free, no API key) -> device top bar (icon + °C + humidity).

Only the chosen city's coordinates are sent to open-meteo.com; nothing else about the user."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from . import errors
from .config import Settings
from .state.manager import DeviceStateManager

log = logging.getLogger("pip.weather")
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
REFRESH_S = 15 * 60

# device icon ids: 0 sun, 1 cloud, 2 rain, 3 snow, 4 storm, 5 fog
def icon_for(code: int) -> int:
    if code == 0:
        return 0
    if code in (45, 48):
        return 5
    if code in (71, 73, 75, 77, 85, 86):
        return 3
    if code >= 95:
        return 4
    if 51 <= code <= 67 or 80 <= code <= 82:
        return 2
    return 1


def default_city(tz: str) -> str:
    return tz.split("/")[-1].replace("_", " ")


async def geocode(client: httpx.AsyncClient, name: str) -> list[dict[str, Any]]:
    r = await client.get(GEOCODE, params={"name": name, "count": 5, "language": "en", "format": "json"})
    r.raise_for_status()
    return [{"name": g["name"], "admin1": g.get("admin1", ""), "country": g.get("country", ""),
             "latitude": g["latitude"], "longitude": g["longitude"]} for g in r.json().get("results", [])]


class WeatherService:
    def __init__(self, settings: Settings, manager: DeviceStateManager) -> None:
        self.s = settings
        self.m = manager
        self.last_error = ""
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    def location(self) -> dict[str, Any]:
        return dict(self.s.prefs().get("weather_location") or {})

    async def resolve_default(self, client: httpx.AsyncClient) -> dict[str, Any] | None:
        loc = self.location()
        if loc:
            return loc
        hits = await geocode(client, default_city(self.s.pip_timezone))
        if not hits:
            return None
        loc = hits[0]
        self.s.save_prefs(weather_location=loc)
        return loc

    async def refresh(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as c:
            loc = await self.resolve_default(c)
            if not loc:
                raise RuntimeError("no weather location")
            r = await c.get(FORECAST, params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                                              "current": "temperature_2m,relative_humidity_2m,weather_code",
                                              "timezone": "auto"})
            r.raise_for_status()
            cur = r.json()["current"]
        w = {"out_temp_c10": int(round(float(cur["temperature_2m"]) * 10)), "out_hum": int(cur["relative_humidity_2m"]),
             "out_code": icon_for(int(cur["weather_code"])), "wmo_code": int(cur["weather_code"]),
             "place": loc["name"], "updated": datetime.now(UTC).isoformat()}
        with self.m.lock:
            self.m.weather = w
            self.m.changed("weather_updated")
        self.last_error = ""
        return w

    def poke(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as e:  # offline PC, API down: keep the last reading, log, retry later
                self.last_error = f"{type(e).__name__}: {e}"[:160]
                errors.report(self.m.db, "weather", "Weather refresh failed", self.last_error)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), REFRESH_S)
            except TimeoutError:
                pass

    def start(self) -> None:
        if self.s.pip_weather:
            self._task = asyncio.create_task(self.run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
