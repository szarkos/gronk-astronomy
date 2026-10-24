#!/usr/bin/env python3
"""What's up tonight: interesting deep-sky targets above a min altitude, with Moon data.

Live calls per run: 2 (GET /solar-system/times, GET /targets/search), 2-4 s apart.
Moon illumination, Moon RA/Dec and target-Moon separation are computed locally
with astropy (the API's search results also carry a per-window Moon distance
and illumination, shown alongside for comparison).

Examples
  .venv/bin/python whats_up_tonight.py --lat 37.7378 --lon -113.6975 \
      --tz America/Denver --date 2026-10-24 --min-alt 30
  ... --types GXY,PNEB --max-mag 11 --limit 15 --json
  ... --offline  (re-render from samples/ cache, no network)
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date as Date, datetime as DT, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")
from astropy.utils import iers  # noqa: E402
iers.conf.auto_download = False  # never phone home for IERS tables
import astropy.units as u  # noqa: E402
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body  # noqa: E402
from astropy.time import Time  # noqa: E402

from client import SAMPLES_DIR, TelescopiusAuthError, TelescopiusClient, TelescopiusError  # noqa: E402


def local_dt(day: Date, hhmm: str | None, tz: ZoneInfo, *, evening_anchor: bool = True) -> DT | None:
    """Turn an 'HH:MM' night-time string into an aware datetime. Times before
    noon are taken to be after midnight, i.e. on day+1."""
    if not hhmm or ":" not in hhmm:
        return None
    h, m = (int(x) for x in hhmm.split(":")[:2])
    d = day + timedelta(days=1) if (evening_anchor and h < 12) else day
    return DT(d.year, d.month, d.day, h, m, tzinfo=tz)


def moon_state(when: DT, loc: EarthLocation) -> dict:
    t = Time(when)
    moon = get_body("moon", t, loc)
    sun = get_body("sun", t, loc)
    elong = sun.separation(moon).rad
    # phase angle i (Meeus 48.2 approximation is fine for illumination to ~0.1%)
    import math
    r_sun = sun.distance.to(u.km).value
    r_moon = moon.distance.to(u.km).value
    i = math.atan2(r_sun * math.sin(elong), r_moon - r_sun * math.cos(elong))
    illum = (1 + math.cos(i)) / 2
    aa = moon.transform_to(AltAz(obstime=t, location=loc))
    return {"moon": moon, "illum": illum, "alt": float(aa.alt.deg),
            "ra_h": float(moon.ra.hour), "dec": float(moon.dec.deg)}


def separation_deg(moon, ra_h: float, dec: float) -> float:
    tgt = SkyCoord(ra=ra_h * 15 * u.deg, dec=dec * u.deg, frame="icrs")
    return float(moon.separation(tgt.transform_to(moon.frame)).deg) if hasattr(moon, "frame") else float("nan")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--date", default=Date.today().isoformat(), help="YYYY-MM-DD (evening of)")
    ap.add_argument("--min-alt", type=float, default=30.0)
    ap.add_argument("--tz", default="UTC", help="IANA timezone, e.g. America/Denver")
    ap.add_argument("--types", default="GXY,ENEB,RNEB,PNEB,SNR",
                    help="Telescopius type codes, comma-separated (accepted live: DEEP_SKY_OBJECT, GXY, ENEB, PNEB, RNEB, SNR; rejected: GCL, OCL)")
    ap.add_argument("--max-mag", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=20, help="1-120")
    ap.add_argument("--order", default="mag", help="API sort field (mag, size, transit, imaging_time, popularity, ...)")
    ap.add_argument("--desc", action="store_true", help="sort descending (default ascending, i.e. brightest first for mag)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true", help="use cached samples/ instead of the API")
    a = ap.parse_args(argv)

    tz = ZoneInfo(a.tz)
    day = Date.fromisoformat(a.date)
    loc = EarthLocation(lat=a.lat * u.deg, lon=a.lon * u.deg)
    tag = f"{a.lat:.4f}_{a.lon:.4f}_{a.date}"
    site = dict(lat=a.lat, lon=a.lon, timezone=a.tz, datetime=a.date)

    if a.offline:
        times = json.loads((SAMPLES_DIR / f"cli_times_{tag}.json").read_text())["response"]
        res = json.loads((SAMPLES_DIR / f"cli_search_{tag}.json").read_text())["response"]
        calls = []
    else:
        try:
            with TelescopiusClient(cache_dir=SAMPLES_DIR, max_calls=2) as c:
                times = c.get_solar_system_times(**site, cache_name=f"cli_times_{tag}")
                res = c.search_targets(types=a.types, **site, min_alt=a.min_alt, mag_max=a.max_mag,
                                       mag_unknown=False, order=a.order, order_asc=not a.desc,
                                       results_per_page=max(1, min(a.limit, 120)),
                                       hour_min="astronomical_sunset", hour_max="astronomical_sunrise",
                                       cache_name=f"cli_search_{tag}")
                calls = c.calls
        except TelescopiusAuthError as e:
            print(f"API key rejected ({e.status_code}). Not retrying.", file=sys.stderr)
            return 2
        except TelescopiusError as e:
            print(f"API error: {e}", file=sys.stderr)
            return 1

    tw = times.get("sun", {}).get("twilights", {})
    dusk = local_dt(day, tw.get("astronomical_sunset"), tz)
    dawn = local_dt(day, tw.get("astronomical_sunrise"), tz)
    midnight = local_dt(day, tw.get("midnight"), tz) or DT(day.year, day.month, day.day, 23, 59, tzinfo=tz)
    m_mid = moon_state(midnight, loc)
    mt = times.get("moon", {})

    rows = []
    for item in res.get("page_results", []):
        o = item.get("object", {})
        tr = item.get("transit_observation", {}) or {}
        vis = item.get("tonight_visibility", {}) or {}
        win = (vis.get("windows") or [{}])[0]
        ra_h, dec = o.get("ra"), o.get("dec")
        transit_local = local_dt(day, (item.get("tonight_times") or {}).get("transit"), tz)
        # evaluate the Moon at transit if transit is inside the dark window, else at local midnight
        when = transit_local if (transit_local and dusk and dawn and dusk <= transit_local <= dawn) else midnight
        ms = m_mid if when == midnight else moon_state(when, loc)
        sep = separation_deg(ms["moon"], ra_h, dec) if ra_h is not None else None
        rows.append({
            "name": o.get("main_name") or o.get("main_id"),
            "id": o.get("main_id"),
            "types": [t for t in o.get("types", []) if t not in ("deep_sky_object",)][:3],
            "con": o.get("con"),
            "mag": tr.get("mag") if tr.get("mag") not in (0, None) else o.get("visual_mag"),
            "size_arcmin": round(o["major_axis"] / 60, 1) if o.get("major_axis") else None,  # major_axis looks like arcsec (M31 = 11346)
            "ra_h": ra_h, "dec": dec,
            "max_alt": vis.get("max_altitude"), "max_alt_time": vis.get("max_altitude_hour"),
            "transit": (item.get("tonight_times") or {}).get("transit"),
            "window": f"{win.get('start')}-{win.get('end')}" if win else None,
            "imaging_h": win.get("imaging_time_hours"),
            "moon_sep_deg": round(sep, 1) if sep is not None else None,
            "moon_sep_eval_at": when.strftime("%H:%M"),
            "moon_alt_then": round(ms["alt"], 1),
            "api_moon_dist_deg": win.get("moon_distance_deg"),
            "api_moon_illum": win.get("moon_illumination_percent"),
            "url": o.get("url"),
        })

    out = {
        "site": {"lat": a.lat, "lon": a.lon, "tz": a.tz, "date": a.date, "min_alt": a.min_alt,
                 "types": a.types, "max_mag": a.max_mag},
        "night": {"sunset": tw.get("sunset"), "astro_dusk": tw.get("astronomical_sunset"),
                  "midnight": tw.get("midnight"), "astro_dawn": tw.get("astronomical_sunrise"),
                  "sunrise": tw.get("sunrise")},
        "moon": {"rise": mt.get("rise"), "transit": mt.get("transit"), "set": mt.get("set"),
                 "illumination_pct_at_midnight": round(m_mid["illum"] * 100, 1),
                 "alt_at_midnight_deg": round(m_mid["alt"], 1),
                 "ra_h": round(m_mid["ra_h"], 3), "dec_deg": round(m_mid["dec"], 2)},
        "matched": res.get("matched"),
        "targets": rows,
        "api_calls": [{k: v for k, v in c.items() if k != "params"} for c in calls],
    }
    if a.json:
        print(json.dumps(out, indent=1))
        return 0

    n, m = out["night"], out["moon"]
    print(f"Tonight {a.date} at {a.lat}, {a.lon} ({a.tz})  min alt {a.min_alt:g} deg  types={a.types}  mag<={a.max_mag:g}")
    print(f"  Sun set {n['sunset']}  astro dark {n['astro_dusk']} -> {n['astro_dawn']}  (midnight {n['midnight']})  rise {n['sunrise']}")
    print(f"  Moon rise {m['rise']}  transit {m['transit']}  set {m['set']}  "
          f"illum {m['illumination_pct_at_midnight']}% @ midnight, alt {m['alt_at_midnight_deg']} deg")
    print(f"  API matched {out['matched']} objects; showing {len(rows)} (order={a.order}, {'desc' if a.desc else 'asc'})\n")
    hdr = f"{'#':>2} {'Target':<26} {'Type':<14} {'Con':<4} {'Mag':>5} {'MaxAlt':>6} {'@':>5} {'Transit':>7} {'Window':<11} {'Img h':>5} {'MoonSep':>7} {'(API)':>6} {'MoonAlt':>7}"
    print(hdr); print("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        mag = f"{r['mag']:.1f}" if isinstance(r["mag"], (int, float)) else "-"
        print(f"{i:>2} {str(r['name'])[:26]:<26} {','.join(r['types'])[:14]:<14} {str(r['con'] or ''):<4} {mag:>5} "
              f"{str(r['max_alt'] or '-'):>6} {str(r['max_alt_time'] or ''):>5} {str(r['transit'] or ''):>7} "
              f"{str(r['window'] or ''):<11} {str(r['imaging_h'] or ''):>5} {str(r['moon_sep_deg']):>7} "
              f"{str(r['api_moon_dist_deg'] or ''):>6} {str(r['moon_alt_then']):>7}")
    print("\nMoonSep = local astropy separation at the target's transit (or midnight if transit is outside astro dark);"
          "\n(API) = Telescopius window moon_distance_deg; MoonAlt = Moon altitude at that same instant.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
