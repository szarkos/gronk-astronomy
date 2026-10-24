"""Offline checks: no network. Run: .venv/bin/python test_offline.py"""
import json, os, subprocess, sys
from pathlib import Path
HERE = Path(__file__).parent

def test_cli_offline():
    out = subprocess.run([sys.executable, "whats_up_tonight.py", "--lat", "37.7378", "--lon", "-113.6975",
                          "--tz", "America/Denver", "--date", "2026-10-24", "--min-alt", "30", "--offline", "--json"],
                         cwd=HERE, capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    assert d["targets"], "no targets"
    assert 90 < d["moon"]["illumination_pct_at_midnight"] <= 100
    for t in d["targets"]:
        assert t["max_alt"] >= 30
        if t["api_moon_dist_deg"] is not None:
            assert abs(t["moon_sep_deg"] - t["api_moon_dist_deg"]) < 3, t

def test_no_key_in_samples():
    key = os.environ.get("TELESCOPIUS_API_KEY")
    for p in (HERE / "samples").glob("*"):
        txt = p.read_text(errors="ignore")
        if key:
            assert key not in txt, f"key leaked in {p.name}"

def test_client_repr_hides_key():
    sys.path.insert(0, str(HERE)); from client import TelescopiusClient
    c = TelescopiusClient(api_key="dummy-not-real-123")
    assert "dummy-not-real-123" not in repr(c)

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)
