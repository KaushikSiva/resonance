"""
Real-time context for RESONANCE: current local temperature + conditions.

Fetched through Bright Data when a proxy is configured (env BRIGHTDATA_PROXY =
http://user:pass@brd.superproxy.io:33335), otherwise fetched directly. Location comes from
IP geolocation (also via Bright Data when configured). Everything degrades gracefully to
'—' if offline, so the show never blocks on the network.
"""
import json
import os
import ssl
import threading
import time
import urllib.request

WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle", 61: "rain", 63: "rain", 65: "heavy rain",
    71: "snow", 73: "snow", 75: "snow", 80: "showers", 81: "showers", 82: "showers",
    95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm",
}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _get(url, timeout=6):
    proxy = os.environ.get("BRIGHTDATA_PROXY")               # route through Bright Data when set
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
            urllib.request.HTTPSHandler(context=_CTX))
    else:
        opener = urllib.request.build_opener()
    req = urllib.request.Request(url, headers={"User-Agent": "resonance/1.0"})
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _locate():
    try:
        d = _get("http://ip-api.com/json/?fields=lat,lon,city,regionName")
        return d["lat"], d["lon"], d.get("city") or d.get("regionName") or "here"
    except Exception:
        return 37.7749, -122.4194, "San Francisco"           # sensible default (SF)


def fetch():
    lat, lon, city = _locate()
    try:
        d = _get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                 f"&current=temperature_2m,weather_code&temperature_unit=fahrenheit")
        cur = d["current"]
        return {
            "city": city,
            "temp_f": round(cur["temperature_2m"]),
            "condition": WEATHER_CODES.get(cur["weather_code"], "—"),
            "via": "Bright Data" if os.environ.get("BRIGHTDATA_PROXY") else "direct",
        }
    except Exception as e:
        return {"city": city, "temp_f": None, "condition": "offline", "via": str(e)[:30]}


class Live:
    """Background poller — refreshes the weather every few minutes without blocking the loop."""
    def __init__(self, period=300):
        self.data = {"city": "…", "temp_f": None, "condition": "…", "via": ""}
        self.period = period
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            self.data = fetch()
            time.sleep(self.period)


if __name__ == "__main__":
    print(fetch())
