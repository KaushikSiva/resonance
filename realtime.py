"""
Real-time context for RESONANCE: current local weather + the song's live view count.

Weather is fetched through **Bright Data's SERP API** (Google's weather widget) when a token is
configured, which is the real integration; it falls back to Open-Meteo direct otherwise. The
YouTube view count is scraped from the watch page (direct — the unlocker zone needs KYC for
youtube.com). Everything degrades to '—' if offline, so the show never blocks on the network.
"""
import json
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


_load_env()
TOKEN = os.environ.get("BRIGHTDATA_API_TOKEN")
SERP_ZONE = os.environ.get("BRIGHTDATA_SERP_ZONE", "serp_api1")
UNLOCKER_ZONE = os.environ.get("BRIGHTDATA_UNLOCKER_ZONE", "mcp_unlocker")
BRD_API = "https://api.brightdata.com/request"


def _brd(zone, url, timeout=25):
    """Fetch a URL through Bright Data's API (SERP or Web Unlocker zone)."""
    body = json.dumps({"zone": zone, "url": url, "format": "raw"}).encode()
    req = urllib.request.Request(BRD_API, data=body, headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(errors="replace")


def _direct(url, timeout=8, ua="resonance/1.0"):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.build_opener(urllib.request.HTTPSHandler(context=_CTX)).open(req, timeout=timeout) as r:
        return r.read().decode(errors="replace")


# ---------------------------------------------------------------- weather

def _weather_brightdata(city):
    q = urllib.parse.quote(f"weather {city}")
    data = json.loads(_brd(SERP_ZONE, f"https://www.google.com/search?q={q}&brd_json=1"))
    w = data.get("weather") or {}
    temp = w.get("temperature_alt") or w.get("temperature") or ""
    f = re.search(r"(\d+)", temp)
    cond = (w.get("subtitles") or ["", "—"])[-1].lower()
    return {"city": city, "temp_f": int(f.group(1)) if f else None, "condition": cond, "via": "Bright Data"}


def _weather_direct(city="San Francisco", lat=37.7749, lon=-122.4194):
    d = json.loads(_direct(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                           f"&current=temperature_2m,weather_code&temperature_unit=fahrenheit"))
    codes = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
             61: "rain", 63: "rain", 65: "heavy rain", 80: "showers", 95: "thunderstorm"}
    c = d["current"]
    return {"city": city, "temp_f": round(c["temperature_2m"]),
            "condition": codes.get(c["weather_code"], "—"), "via": "direct"}


def weather():
    city = os.environ.get("WEATHER_CITY", "San Francisco")
    if TOKEN:
        try:
            return _weather_brightdata(city)
        except Exception:
            pass
    try:
        return _weather_direct(city)
    except Exception as e:
        return {"city": city, "temp_f": None, "condition": "offline", "via": str(e)[:24]}


# ---------------------------------------------------------------- song views

def song_views(video_id):
    try:
        html = _direct(f"https://www.youtube.com/watch?v={video_id}", ua="Mozilla/5.0")
        m = re.search(r'"viewCount":"(\d+)"', html)
        return int(m.group(1)) if m else None
    except Exception:
        return None


# ---------------------------------------------------------------- poller

class Live:
    def __init__(self, video_id=None, period=300):
        self.video_id = video_id
        self.data = {"city": "…", "temp_f": None, "condition": "…", "via": "", "views": None}
        self.period = period
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            d = weather()
            if self.video_id:
                d["views"] = song_views(self.video_id)
            self.data = d
            time.sleep(self.period)


if __name__ == "__main__":
    print(weather())
    print("views:", song_views("HMqgVXSvwGo"))
