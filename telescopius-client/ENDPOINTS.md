# Telescopius API v2.2: endpoints used and observed response shapes

* **Base URL:** `https://api.telescopius.com/v2.2`. This comes from the official OpenAPI 3.1 spec served at https://api.telescopius.com/. A copy is in `samples/openapi_v2.2.json`.
* **Auth:** every request sends the header `Authorization: Key <API key>`. That's security scheme `APIKeyHeader` in the spec. The key is read from `$TELESCOPIUS_API_KEY`, and it never goes in the URL, the logs or `samples/`.
* **Method:** every endpoint below is a `GET` with query parameters.
* **Errors:** the spec documents 400, 401 and 429 for most endpoints. Validation errors look like this:
  `{"error":{"status":400,"code":"VALIDATION_ERROR","message":"Invalid types [GCL, OCL]","details":{}}}`
* **Booleans:** the client sends booleans as `1`/`0`.
* **Times:** all times are local `"HH:MM"` strings (24hr by default) in the requested `timezone`.

The raw responses below were captured live on 2026-10-24 for iTelescope Utah (lat 37.7378, lon -113.6975, America/Denver). They're in `samples/<name>.json`, with a `_request` block (URL, params, status, auth header redacted) and a `response` block. The types listed are the ones observed. "number" means the field held an int in some rows and a float in others.

## Live call log (11 calls total, 2-4 s apart, no retries)

| # | Endpoint | Status | Sample file |
|---|----------|--------|-------------|
| 1 | `/quote-of-the-day` | 200 | `quote_of_the_day.json` |
| 2 | `/solar-system/times` | 200 | `solar_system_times_utah_2026-10-24.json` |
| 3 | `/targets/search` (`types=...,GCL,OCL`) | **400** (`Invalid types [GCL, OCL]`) | none |
| 4 | `/targets/highlights` | 200 | `targets_highlights_utah_2026-10-24.json` |
| 5 | `/weather/forecast` | 200 | `weather_forecast_utah.json` |
| 6 | `/events/calendar` | 200 | `events_calendar_2026-10-24_30d.json` |
| 7 | `/events/highlights` | 200 | `events_highlights_2026-10-24_30d.json` |
| 8-9 | CLI run 1: times + search (`DEEP_SKY_OBJECT`, `order=popularity` desc) | 200, 200 | `cli_search_run1_DSO_popularity_*.json`, `tonight_utah_run1_DSO_popularity.txt` |
| 10-11 | CLI run 2 (final defaults): times + search | 200, 200 | `cli_times_*.json`, `cli_search_*.json`, `tonight_utah.txt` |

---

## GET /quote-of-the-day  (`client.get_quote_of_the_day()`)
* **Params:** none. This is the cheapest way to check the key.
* **Response:** `{text: str, author: str}`

## GET /solar-system/times  (`client.get_solar_system_times()`, alias `client.sky_times()`)
* **Params:**
  * `lat`, `lon`, `timezone`, `datetime` (`YYYY-MM-DD` or `YYYY-MM-DD HH:mm:ss`)
  * `time_format` (`24hr` or `ampm`)
  * `atmospheric_refraction` (bool, default true)
  * `partner_observatory` (MPC code), `partner_telescope`
  * If you leave out `lat`/`lon`/`timezone`, the API geolocates you by IP.
* **Response:**
```
{
  sun:  {rise: str, transit: str, set: str,
         twilights: {noon, sunset, civil_sunset, nautical_sunset, astronomical_sunset,
                     astronomical_sunrise, nautical_sunrise, civil_sunrise, sunrise,
                     midnight, darkest_sunset, darkest_sunrise}: str},
  moon: {rise: str, transit: str, set: str},
  mercury|venus|mars|jupiter|saturn|uranus|neptune: {rise: str, transit: str, set: str}
}
```
* **Utah sample, 2026-10-24:**
  * Sun sets 18:45. Astronomical dark runs 20:13 to 06:24, and astronomical midnight is 01:19.
  * Moon rises 17:45, transits 00:26 and sets 07:19.
* **Not returned:** Moon phase, illumination, RA/Dec and planet positions. The SDK README's `times['moon']['phase']` doesn't exist. `whats_up_tonight.py` computes these locally with astropy.

## GET /targets/search  (`client.search_targets()`)
* **Required:** `types`.
  * Accepted live: `DEEP_SKY_OBJECT`, `GXY`, `ENEB`, `RNEB`, `PNEB`, `SNR`.
  * **Rejected:** `GCL` and `OCL`, even though the SDK README lists them. The spec doesn't enumerate the codes. Objects carry lowercase internal types such as `opcl`, `gxy`, `eneb`, `rneb`, `dkneb`, `h2r`, but whether those work as filters is untested.
* **Location and time:** `lat`, `lon`, `timezone`, `datetime`, `time_format`, `atmospheric_refraction`, `partner_observatory`, `partner_telescope`.
* **Filters:**
  * `name`, `name_exact`, `con` (IAU codes, comma-separated), `cat`
  * `mag_min`, `mag_max`, `mag_unknown`
  * `size_min`, `size_max`, `size_unknown`. The spec doesn't state the units. The response's `major_axis` looks like arcsec (M 31 = 11346, about 189′).
  * `subr_min`, `subr_max`, `subr_unknown`
  * `ra_min`, `ra_max` (hours), `dec_min`, `dec_max`
  * `min_alt`, `min_alt_minutes`, `az_quadrants` (NE, NW, SW, SE)
  * `hour_min`, `hour_max`: a number in [0, 24), or one of `sunset`, `civil_sunset`, `nautical_sunset`, `astronomical_sunset`, `darkest_sunset` and their `*_sunrise` counterparts.
  * `moon_dist_min` (degrees, or `narrowband`, `ha_s2`, `o3`, `lrgb`), `moon_dist_max`
  * `center_ra`, `center_dec`, `dist_min`, `dist_max`
  * `comet_orbit`
* **Output:**
  * `compute_current` (0/1)
  * `ephemeris` (`daily` or `yearly`), `ephemeris_hour`
  * `order`: `name`, `con`, `dec`, `mag`, `ra`, `rise`, `set`, `transit`, `size`, `subr`, `type` or `imaging_time`. The spec says DSOs also accept `popularity` and `opposition`.
  * `order_asc`
  * `results_per_page` (1-120, default 10), `page`
* **Response:**
```
{
  matched: int,
  page_results: [{
    object: {main_id: str, main_name: str, ids: [str], names: [str], alt_ids: [str],
             family: str ("deep_sky_object"), types: [str], url: str,
             main_image_url: str, thumbnail_url: str,
             ra: float (hours), dec: float (deg), con: str, con_name: str,
             visual_mag?: number, photo_mag?: number, major_axis?: int, minor_axis?: int,
             pa_east?: int, redshift?: number, subr?: number, morph_class?: str},
    tonight_times: {rise: str, transit: str, set: str},
    transit_observation: {ra: float, dec: float, dist_au: number, alt: float, az: number,
                          mag: number (0 when unknown), con: str},
    tonight_visibility: {max_altitude: int, max_altitude_hour: str,
                         windows: [{start: str, end: str, imaging_time_hours: float,
                                    moon_illumination_percent: float,   // a 0-1 FRACTION despite the name (0.99)
                                    moon_distance_deg: float}]}
  }]
}
```
* **Notes:**
  * The API does give a Moon distance and illumination for each window. The CLI shows them next to its own astropy separation, which is computed at the target's transit. The two agreed to within about 1.4° in the samples.
  * Run 1 used `types=DEEP_SKY_OBJECT` and `order=popularity` with `order_asc=0`. The results came back sorted by magnitude descending (10.0 down to 8.0), mostly HEN 3 emission-line stars. In practice `popularity` didn't change the order, so the CLI now defaults to `order=mag` ascending with nebula and galaxy types.
  * Reflection nebulae (VDB) carry the magnitude of the star that illuminates them, so they rank near the top on `mag`.

## GET /targets/highlights  (`client.get_target_highlights()`)
* **Params:** the same location and time params as search, plus `types` (required), `min_alt`, `min_alt_minutes`, `moon_dist_min`, `moon_dist_max`, `compute_current` and `ephemeris`.
* **Response:** the same shape as `/targets/search`. The Utah sample returned `matched: 24` and 10 results, mostly Cassiopeia dark and reflection nebulae (LDN 1355, VDB 9, ...).

## GET /weather/forecast  (`client.get_weather_forecast()`)
* **Required:** `lat`, `lon`, `timezone`.
* **Optional:** `temp_unit` (c/f), `speed_unit` (kmh/mph), `precip_unit` (mm/in), `include_hourly` (bool).
* **Refresh rate:** the spec says the data updates every 4-6 hours, so cache it locally.
* **Response:**
```
{ daily: [ {label: str ("Saturday 24"), date: "YYYY-MM-DD", day_length_hours: float, night_length_hours: float,
            sun_times: {same 12 twilight keys as /solar-system/times},
            nighttime_stats|daytime_stats|all_day_stats: {
               moon_illumination: int (%), precipitation_chance: int, total_cloud_cover: int,
               seeing: int, transparency: int, atmospheric_stability: int, relative_humidity: int,
               surface_wind: int, temperature: int, dew_risk: str ("high"), condition: str ("PARTLY_CLOUDY")},
            periods: [{label: str, time_of_day: str (AFTERNOON|EVENING|MIDNIGHT|PREDAWN), stats: {...same...}}]
          } x7 ] }
```
* **Utah tonight:** 21% cloud, 7% chance of precipitation, seeing 60, transparency 79, 99% Moon, high dew risk.

## GET /events/calendar  (`client.get_events_calendar()`)
* **Params:**
  * `date` with `days` (7-365, default 30), or `year` with `month`
  * `lat`, `lon`, `elevation`, `timezone`
  * `categories`: any of moon, planets, meteor_showers, eclipses, conjunctions, seasons
  * `max_conjunction_deg`, `conjunction_frame`
* **Response:**
```
{ days: int, total_events: int,
  events: [{type: str, name: str, object?: str, objects?: [str], timestamp: int (unix s), datetime: ISO-UTC str,
            highlight_tier: int, ...type-specific: moon_phase, distance_km, is_supermoon, is_micromoon,
            is_blue_moon, is_black_moon, traditional_name, deg, is_occultation, geographic_regions,
            visible_locally, moon_altitude}],
  planet_visibility: [{id, name, status, visibility, max_alt, constellation, constellation_code,
                       magnitude, evening_altitude, morning_altitude, midnight_altitude}],
  planet_alignments: {type, name, datetime, timestamp, planets: [str], count, angular_span, period,
                      start_date, end_date, highlight_tier} }
```
* **Sample:** 24 events, including Full "Hunter's" Moon at 2026-10-26T04:12Z (2026-10-25 22:12 MDT) and Venus inferior conjunction on 10-24.
* **Timestamps:** these are in UTC, so convert them to the site's zone before showing them.

## GET /events/highlights  (`client.get_events_highlights()`)
* **Params:** `date`, `days` (1-365), `limit` (1-50, default 10), `year`, `month`, `lat`, `lon`, `elevation`, `timezone`, `max_conjunction_deg`, `conjunction_frame`.
* **Response:** `{date: str, days: int, days_ahead: int, count: int, events: [same event objects as calendar]}`
* **Sample:** lunar occultations of Mars and Jupiter, the Southern and Northern Taurids, the Leonids, New Moon, and others.

## Not exercised (no live calls made)
* `/targets/lists`, `/targets/lists/{id}`, `/target-lists`, `/target-lists/{id}`: the account's saved lists. `client.get_target_lists()` is implemented but wasn't called.
* `/equipment/user` (+ sub-resources), `/news/global`, `/mcp` (POST).
* `/pictures/search`: this is in the SDK but **not in the v2.2 spec**, so it isn't implemented.
