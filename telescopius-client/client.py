"""Thin, polite client for the Telescopius REST API v2.2.

Why not the `telescopius-api` PyPI package?  See README.md -> "SDK decision".
Short version: it is an unofficial single-author port, its declared GitHub repo
404s, it targets /v2.0 rather than /v2.2, and it has no weather or events
methods. Method names here mirror that SDK so swapping is trivial.

Auth:   header  "Authorization: Key <API key>"  (from the official OpenAPI spec)
Base:   https://api.telescopius.com/v2.2

The API key is read from the TELESCOPIUS_API_KEY env var. It is never printed,
logged, cached or put in a URL. Errors are re-raised with the key redacted.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.telescopius.com/v2.2"
USER_AGENT = "grok-stonks-telescopius/1.0 (+personal astro planning; python-requests)"
SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


class TelescopiusError(Exception):
    def __init__(self, message: str, status_code: int | None = None, path: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.path = path


class TelescopiusAuthError(TelescopiusError):
    """401/403: key rejected. The client refuses further calls after this."""


def _redact(text: str, secret: str | None) -> str:
    if secret and text:
        text = text.replace(secret, "[REDACTED]")
    # belt and braces: scrub anything that looks like an Authorization header
    return re.sub(r"(Authorization['\"]?\s*[:=]\s*['\"]?Key\s+)[^'\"\s,}]+", r"\1[REDACTED]", text or "")


class TelescopiusClient:
    """One request at a time, 2-4 s apart, no retries.

    Args:
        api_key: defaults to os.environ["TELESCOPIUS_API_KEY"].
        min_delay/max_delay: random pause (seconds) enforced between calls.
        cache_dir: if set, each raw JSON response is written there as
            <name>.json (never contains the key).
        max_calls: hard ceiling on live calls for this client instance.
    """

    def __init__(self, api_key: str | None = None, *, base_url: str = BASE_URL,
                 min_delay: float = 2.0, max_delay: float = 4.0, timeout: float = 30.0,
                 cache_dir: str | Path | None = None, max_calls: int = 15):
        self._key = api_key or os.environ.get("TELESCOPIUS_API_KEY")
        if not self._key:
            raise TelescopiusError("TELESCOPIUS_API_KEY is not set")
        self.base_url = base_url.rstrip("/")
        self.min_delay, self.max_delay = min_delay, max_delay
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_calls = max_calls
        self.calls: list[dict[str, Any]] = []  # [{path, params, status, elapsed_s}]
        self._last = 0.0
        self._auth_failed = False
        self._s = requests.Session()
        self._s.headers.update({"Authorization": f"Key {self._key}",
                                "Accept": "application/json",
                                "User-Agent": USER_AGENT})

    def __repr__(self) -> str:  # never expose the key
        return f"<TelescopiusClient base_url={self.base_url!r} calls={len(self.calls)}>"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self._s.close()

    # ------------------------------------------------------------------ core
    def _get(self, path: str, params: dict[str, Any] | None = None, *, cache_name: str | None = None) -> Any:
        if self._auth_failed:
            raise TelescopiusAuthError("Key was rejected earlier; refusing further calls", 401, path)
        if len(self.calls) >= self.max_calls:
            raise TelescopiusError(f"max_calls={self.max_calls} reached; not calling {path}")
        clean = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            clean[k] = (1 if v else 0) if isinstance(v, bool) else v
        wait = self._last + random.uniform(self.min_delay, self.max_delay) - time.monotonic()
        if self._last and wait > 0:
            time.sleep(wait)
        t0 = time.monotonic()
        try:
            r = self._s.get(self.base_url + path, params=clean, timeout=self.timeout)
        except requests.RequestException as e:  # no retry
            self._last = time.monotonic()
            self.calls.append({"path": path, "params": clean, "status": None, "error": type(e).__name__})
            raise TelescopiusError(_redact(f"Network error on {path}: {e}", self._key), None, path) from None
        finally:
            self._last = time.monotonic()
        self.calls.append({"path": path, "params": clean, "status": r.status_code,
                           "elapsed_s": round(time.monotonic() - t0, 2)})
        if r.status_code in (401, 403):
            self._auth_failed = True
            raise TelescopiusAuthError(_redact(f"{r.status_code} on {path}: {r.text[:300]}", self._key), r.status_code, path)
        if r.status_code >= 400:
            raise TelescopiusError(_redact(f"{r.status_code} on {path}: {r.text[:500]}", self._key), r.status_code, path)
        try:
            data = r.json()
        except ValueError:
            raise TelescopiusError(f"Non-JSON response on {path} (status {r.status_code})", r.status_code, path) from None
        if self.cache_dir and cache_name:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            blob = {"_request": {"method": "GET", "url": self.base_url + path, "params": clean,
                                 "status": r.status_code, "auth": "Authorization: Key [REDACTED]",
                                 "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                    "response": data}
            txt = _redact(json.dumps(blob, indent=1, ensure_ascii=False), self._key)
            (self.cache_dir / f"{cache_name}.json").write_text(txt)
        return data

    # ------------------------------------------------------------ endpoints
    def get_quote_of_the_day(self, **kw) -> dict:
        """GET /quote-of-the-day -> {text, author}. Cheapest auth check."""
        return self._get("/quote-of-the-day", cache_name=kw.get("cache_name"))

    def search_targets(self, *, types: str = "DEEP_SKY_OBJECT", lat: float | None = None,
                       lon: float | None = None, timezone: str | None = None,
                       datetime: str | None = None, min_alt: float | None = None,
                       min_alt_minutes: int | None = None, mag_max: float | None = None,
                       mag_min: float | None = None, size_min: float | None = None,
                       size_max: float | None = None, con: str | None = None,
                       moon_dist_min: float | str | None = None, order: str | None = None,
                       order_asc: bool | None = None, results_per_page: int | None = None,
                       page: int | None = None, compute_current: int | None = None,
                       cache_name: str | None = None, **extra) -> dict:
        """GET /targets/search. `types` is required by the API.

        Size units are not stated in the spec; response major_axis/minor_axis look like arcsec (M 31 major_axis=11346).
        `extra` passes any other documented param
        (hour_min, hour_max, az_quadrants, cat, name, subr_max, ...).
        """
        p = dict(types=types, lat=lat, lon=lon, timezone=timezone, datetime=datetime,
                 min_alt=min_alt, min_alt_minutes=min_alt_minutes, mag_max=mag_max,
                 mag_min=mag_min, size_min=size_min, size_max=size_max, con=con,
                 moon_dist_min=moon_dist_min, order=order, order_asc=order_asc,
                 results_per_page=results_per_page, page=page, compute_current=compute_current)
        p.update(extra)
        return self._get("/targets/search", p, cache_name=cache_name)

    def get_target_highlights(self, *, types: str = "DEEP_SKY_OBJECT", lat=None, lon=None,
                              timezone=None, datetime=None, min_alt=None, min_alt_minutes=None,
                              moon_dist_min=None, cache_name=None, **extra) -> dict:
        """GET /targets/highlights: popular targets near opposition."""
        p = dict(types=types, lat=lat, lon=lon, timezone=timezone, datetime=datetime,
                 min_alt=min_alt, min_alt_minutes=min_alt_minutes, moon_dist_min=moon_dist_min)
        p.update(extra)
        return self._get("/targets/highlights", p, cache_name=cache_name)

    def get_solar_system_times(self, *, lat=None, lon=None, timezone=None, datetime=None,
                               time_format=None, cache_name=None, **extra) -> dict:
        """GET /solar-system/times: sun/moon/planet rise-transit-set + twilight."""
        p = dict(lat=lat, lon=lon, timezone=timezone, datetime=datetime, time_format=time_format)
        p.update(extra)
        return self._get("/solar-system/times", p, cache_name=cache_name)

    sky_times = get_solar_system_times  # alias the user asked for

    def get_weather_forecast(self, *, lat: float, lon: float, timezone: str, temp_unit=None,
                             speed_unit=None, precip_unit=None, include_hourly: bool | None = None,
                             cache_name=None) -> dict:
        """GET /weather/forecast (lat, lon, timezone required). Data refreshes every
        4-6 h upstream; cache locally rather than polling."""
        p = dict(lat=lat, lon=lon, timezone=timezone, temp_unit=temp_unit, speed_unit=speed_unit,
                 precip_unit=precip_unit, include_hourly=include_hourly)
        return self._get("/weather/forecast", p, cache_name=cache_name)

    def get_events_calendar(self, *, date=None, days=None, year=None, month=None, lat=None,
                            lon=None, elevation=None, timezone=None, categories=None,
                            max_conjunction_deg=None, conjunction_frame=None, cache_name=None) -> dict:
        """GET /events/calendar: moon phases, eclipses, showers, conjunctions, seasons.
        days 7-365 (default 30), or year+month. categories e.g. 'moon,planets'."""
        p = dict(date=date, days=days, year=year, month=month, lat=lat, lon=lon, elevation=elevation,
                 timezone=timezone, categories=categories, max_conjunction_deg=max_conjunction_deg,
                 conjunction_frame=conjunction_frame)
        return self._get("/events/calendar", p, cache_name=cache_name)

    def get_events_highlights(self, *, date=None, days=None, limit=None, year=None, month=None,
                              lat=None, lon=None, elevation=None, timezone=None, cache_name=None) -> dict:
        """GET /events/highlights: up to `limit` prioritized events in the next `days`."""
        p = dict(date=date, days=days, limit=limit, year=year, month=month, lat=lat, lon=lon,
                 elevation=elevation, timezone=timezone)
        return self._get("/events/highlights", p, cache_name=cache_name)

    def get_target_lists(self, cache_name=None) -> Any:
        """GET /targets/lists: the account's saved lists."""
        return self._get("/targets/lists", cache_name=cache_name)
