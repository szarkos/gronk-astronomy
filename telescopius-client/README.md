# Telescopius tooling

This is a small, polite Python client for the **Telescopius REST API v2.2**, plus a "what's up tonight" CLI.

## SDK decision: `telescopius-api` from PyPI was inspected and not used

I downloaded the wheel and read its source before running any of it. It's `telescopius-api` 1.0.0, uploaded 2026-01-26.

* **Author:** "Carl Svensson" (PyPI user `csvensson`). It has one release, and there's nothing tying it to Telescopius the company.
* **Repository:** the declared repo `github.com/telescopius/telescopius-api-python` returns **404**. The Telescopius GitHub org has no public repos.
* **Not official:** the official API docs at api.telescopius.com don't mention a Python SDK. The only SDK they link is the npm package, and they explicitly call it the **"Unofficial JavaScript SDK"**. The Python package is a near line-for-line port of that npm package.
* **Wrong version:** it targets `https://api.telescopius.com/v2.0`, not v2.2.
* **Missing endpoints:** it has no methods for `/weather/forecast`, `/events/calendar` or `/events/highlights`. It does have `search_pictures` → `/pictures/search`, which isn't in the v2.2 spec.
* **Wrong docs:** its README lists type codes `GCL` and `OCL`, and the live API rejects both. It also shows `times['moon']['phase']`, which the API doesn't return.
* **The code itself is clean.** It uses only `httpx`, talks only to api.telescopius.com, and has no telemetry, eval or file access. One caveat: if you turn on `debug=True`, it logs full query URLs.

Because of all this, `client.py` is a thin `requests` client written against the **official OpenAPI spec**. The spec is in `samples/openapi_v2.2.json`. Base URL is `https://api.telescopius.com/v2.2`, with the header `Authorization: Key <key>`. The method names mirror the SDK's (`search_targets`, `get_solar_system_times`, `get_target_highlights`, ...), so moving to an official SDK later would be easy if one ever ships.

## Setup
```bash
cd /workspace/artifacts/telescopius
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # already done
test -n "$TELESCOPIUS_API_KEY" && echo set                           # never echo the value
```

## Client
```python
from client import TelescopiusClient
with TelescopiusClient(cache_dir="samples") as c:      # key from $TELESCOPIUS_API_KEY
    t = c.sky_times(lat=37.7378, lon=-113.6975, timezone="America/Denver", datetime="2026-10-24")
    r = c.search_targets(types="GXY,PNEB", lat=37.7378, lon=-113.6975, timezone="America/Denver",
                         datetime="2026-10-24", min_alt=30, mag_max=11, con="AND,CAS",
                         size_min=None, order="mag", results_per_page=20)
    w = c.get_weather_forecast(lat=37.7378, lon=-113.6975, timezone="America/Denver")
    e = c.get_events_calendar(date="2026-10-24", days=30, categories="moon,planets")
```

The client:

* sends one request at a time, with a random 2-4 s gap between calls
* never retries
* stops after a `max_calls` ceiling (default 15)
* refuses any further calls once it gets a 401 or 403 (`TelescopiusAuthError`)
* redacts the key from error text
* writes each raw response, when you pass `cache_name=`, to `samples/<cache_name>.json` with the auth header shown as `[REDACTED]`

## CLI
```bash
.venv/bin/python whats_up_tonight.py --lat 37.7378 --lon -113.6975 --tz America/Denver \
    --date 2026-10-24 --min-alt 30 [--types GXY,ENEB,RNEB,PNEB,SNR] [--max-mag 10] \
    [--limit 20] [--order mag] [--desc] [--json] [--offline]
```

* **Live calls:** two per run, `/solar-system/times` and `/targets/search`. The search uses `hour_min=astronomical_sunset` and `hour_max=astronomical_sunrise`.
* **Output:** the night's twilight times; the Moon's rise, transit and set; the Moon's illumination % and altitude at astronomical midnight; and, for each target:
  * max altitude and the time it's reached
  * transit time
  * the dark window and imaging hours
  * **Moon separation**, computed locally with astropy at the target's transit (or at midnight if transit falls outside astronomical dark)
  * the API's own `moon_distance_deg`
  * the Moon's altitude at that moment
* **`--offline`:** re-renders from the cached `samples/cli_*` files without touching the network.
* **Sample output:** `samples/tonight_utah.txt`.

## Tests (offline)
`.venv/bin/python test_offline.py` re-runs the CLI from cache, checks that the local Moon separation matches the API's to within 3°, and checks that the key appears nowhere in `samples/`.

## Files
* `client.py`: the API client
* `whats_up_tonight.py`: the CLI
* `probe_endpoints.py`: the one-off probe that made the samples (7 live calls)
* `test_offline.py`
* `ENDPOINTS.md`: params and observed response shapes for each endpoint
* `requirements.txt`
* `samples/`: raw responses, the OpenAPI spec, the probe call log and the CLI outputs

## Gaps
* The type codes for globular and open clusters are unknown. `GCL` and `OCL` are rejected, and the spec doesn't list the valid codes. Use `DEEP_SKY_OBJECT` to include clusters.
* `order=popularity` didn't change the result order in practice.
* `/solar-system/times` returns no Moon phase or position, so those are computed locally.
* The units for `size_min`/`size_max` aren't documented.
* The CLI doesn't call the weather endpoint, to keep it at 2 calls a run. Use `client.get_weather_forecast()` for that.
