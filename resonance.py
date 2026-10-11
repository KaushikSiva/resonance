"""
RESONANCE — a music video you feel (DataFeel), conduct (Infineon radar), and watch react.

  browser plays the song (video + audio) ─▶ reports its playback time
          │                                        │
          ▼                                        ▼
  pre-analyzed timeline (warmth/energy/beats) ─▶ control loop ─▶ DataFeel dot
          ▲                                        │   warm hit on the beat, scaled by YOUR motion
  Infineon radar (your hand = how hard it hits) ───┘   buzz on the beat, LED on the beat
          │
          └─▶ live readings streamed to the dashboard panels

Run:  .venv/bin/python resonance.py            then open http://localhost:8777
      --no-dot / --no-radar to skip a device (simulated instead)
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = "media/fireball.mp4"
PORT = 8777

state = {                                   # everything the dashboard shows, updated by the control loop
    "t": 0.0, "warmth": 0.0, "energy": 0.0, "master": 0.0, "beat": False,
    "skin": 0.0, "led": [0, 0, 0], "buzz": False, "thermal": 0.0,
    "motion": 0.0, "hand": 0.0, "bpm": 0.0, "radar_status": "—",
    "dot_status": "—", "robot": "not connected",
}
play = {"t": 0.0, "wall": time.time(), "playing": False}
subs, subs_lock = [], threading.Lock()


def now_t():
    """Interpolated playback position between the browser's reports (smooth)."""
    return play["t"] + (time.time() - play["wall"] if play["playing"] else 0.0)


# ---------------------------------------------------------------- control loop

def control_loop(timeline, dots, radar, robot, args):
    grid = timeline["grid_hz"]
    warmth, energy, beats = timeline["warmth"], timeline["energy"], timeline["beats"]
    state["bpm"] = timeline["bpm"]
    beat_i = 0
    last_beat_fired = -1.0
    warm_env, led_flash = 0.0, 0.0            # smooth warm swell; LED beat flash that decays
    MAX = args.max

    while True:
        t = now_t()
        if t >= timeline["duration"] - 0.1:                 # loop with the video
            beat_i = 0
        k = min(len(warmth) - 1, max(0, int(t * grid)))
        w, e = warmth[k], energy[k]

        # has a beat passed since last tick?
        while beat_i < len(beats) and beats[beat_i] <= t:
            beat_i += 1
        beat_now = beat_i > 0 and t - beats[beat_i - 1] < 0.12 and beats[beat_i - 1] != last_beat_fired
        if beat_now:
            last_beat_fired = beats[beat_i - 1]
        if t < 0.2:
            beat_i, last_beat_fired = 0, -1.0

        # YOUR motion is the amplifier: a calm hand -> gentle, a moving hand -> it slams
        motion = radar.motion if radar else 0.6
        master = min(1.0, (0.35 + 0.65 * e) * (0.45 + 0.75 * motion))
        state.update(t=round(t, 2), warmth=w, energy=e, master=round(master, 2),
                     motion=round(motion, 2), hand=round(getattr(radar, "hand_cm", 0.0), 0) if radar else 0,
                     bpm=timeline["bpm"],
                     radar_status=(radar.status if radar else "simulated"))

        # The BEAT is carried by vibration + an LED flash (crisp, fast, no sink cost).
        buzz = beat_now and master > 0.25
        if buzz:
            led_flash = 1.0
        led_flash *= 0.80

        # WARMTH is a slow swell: rises through intense/fiery sections, relaxes in the quiet,
        # so you feel the song's dynamics as heat. The sink recovers whenever it dips. Safety caps it.
        drive = master if master > 0.3 else 0.0
        warm_env = 0.90 * warm_env + 0.10 * drive
        thermal = MAX * warm_env if warm_env > 0.08 else 0.0
        state["thermal"] = round(thermal, 2)

        # LED: warm hue (fire), brightness = energy with a flash on every beat
        bright = min(1.0, 0.22 + 0.55 * master + 0.5 * led_flash)
        led = [int(255 * bright), int((70 + 110 * max(0, w)) * bright), int(25 * bright)]
        state["led"] = led
        fire = buzz

        if dots:
            dots.update(thermal, tuple(led), click=fire)
            state["dot_status"] = dots.status
            state["skin"] = round(dots.skin, 1)
        else:
            state["dot_status"], state["skin"] = "simulated", 33.0
        state["beat"] = beat_now
        state["buzz"] = fire

        if robot:                                                # MasterPi dances to the same energy
            robot.drive(master, beat_now, w)
            state["robot"] = robot.status

        push_event(dict(state))
        time.sleep(0.05)


class Robot:
    """Drives the MasterPi over a persistent SSH pipe to dance_daemon.py.
    Auto-reconnects — the robot's Wi-Fi drops often, so a drop just pauses the dance."""

    def __init__(self, host="10.0.0.68", user="pi", key="~/.ssh/masterpi", wheels=False):
        self.host, self.user = host, user
        self.key = os.path.expanduser(key)
        self.wheels = wheels
        self.proc = None
        self.status = "connecting"
        self.last_send = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _spawn(self):
        import subprocess
        opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=6", "-o", "BatchMode=yes"]
        daemon = os.path.join(HERE, "dance_daemon.py")
        subprocess.run(["scp", "-i", self.key, *opts, daemon, f"{self.user}@{self.host}:/tmp/dance_daemon.py"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)   # push latest dance
        cmd = ["ssh", "-i", self.key, *opts, "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
               f"{self.user}@{self.host}", "cd /home/pi/MasterPi && python3 -u /tmp/dance_daemon.py"]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
            self.status = "dancing"
        except Exception:
            self.proc = None
            self.status = "offline"

    def _keepalive(self):
        import subprocess
        while True:
            if self.proc is None or self.proc.poll() is not None:
                self.status = "reconnecting"
                # only try when the host answers, so we don't hang on a dead pipe
                if subprocess.run(["nc", "-z", "-G", "2", self.host, "22"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    self._spawn()
                else:
                    self.status = "offline (robot not reachable)"
            time.sleep(2)

    def drive(self, master, beat, warmth):
        if self.proc is None or self.proc.poll() is not None:
            return
        now = time.time()
        if not beat and now - self.last_send < 0.12:                 # throttle; always send on a beat
            return
        self.last_send = now
        try:
            with self._lock:
                self.proc.stdin.write(json.dumps({"master": round(master, 2),
                                                  "beat": 1 if beat else 0, "warmth": round(warmth, 2)}) + "\n")
                self.proc.stdin.flush()
        except Exception:
            self.proc = None                                         # pipe broke -> keepalive respawns


def push_event(data):
    line = f"data: {json.dumps(data)}\n\n".encode()
    with subs_lock:
        dead = []
        for q in subs:
            try:
                q.append(line)
            except Exception:
                dead.append(q)
        for q in dead:
            subs.remove(q)


# ---------------------------------------------------------------- web server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            body = open(os.path.join(HERE, "resonance.html"), "rb").read()
            return self._send(200, "text/html; charset=utf-8", body)
        if path == "/timeline.json":
            body = open(os.path.join(HERE, VIDEO.rsplit(".", 1)[0] + ".timeline.json"), "rb").read()
            return self._send(200, "application/json", body)
        if path == "/video.mp4":
            return self._serve_video()
        if path == "/events":
            return self._serve_events()
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path == "/time":
            n = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(n) or b"{}")
            play.update(t=float(d.get("t", 0)), wall=time.time(), playing=bool(d.get("playing")))
            return self._send(200, "application/json", b"{}")
        self._send(404, "text/plain", b"not found")

    def _serve_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = []
        with subs_lock:
            subs.append(q)
        try:
            while True:
                if q:
                    self.wfile.write(q.pop(0))
                    self.wfile.flush()
                else:
                    time.sleep(0.02)
        except Exception:
            pass
        finally:
            with subs_lock:
                if q in subs:
                    subs.remove(q)

    def _serve_video(self):
        full = os.path.join(HERE, VIDEO)
        size = os.path.getsize(full)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = int(b) if b else size - 1
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with open(full, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except Exception:
                    break
                remaining -= len(chunk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-dot", action="store_true")
    ap.add_argument("--no-radar", action="store_true")
    ap.add_argument("--robot", action="store_true", help="connect the MasterPi and make it dance")
    ap.add_argument("--robot-host", default="10.0.0.68")
    ap.add_argument("--wheels", action="store_true", help="allow wheel wiggle (robot on the floor, not a table)")
    ap.add_argument("--max", type=float, default=1.0, help="max warm intensity 0..1")
    ap.add_argument("--pulse", type=float, default=2.5, help="warm-hit length seconds")
    args = ap.parse_args()

    import thermoscene as ts
    tl = json.load(open(os.path.join(HERE, VIDEO.rsplit(".", 1)[0] + ".timeline.json")))

    dots = None if args.no_dot else ts.Dots(True, args.max)
    radar = None
    if not args.no_radar:
        try:
            radar = ts.RadarBreath()
        except Exception as e:
            print(f"[radar] not available ({e}) — simulated")
    print(f"[dot] {dots.status if dots else 'off'}   [radar] {'on' if radar else 'sim'}")

    robot = Robot(args.robot_host, wheels=args.wheels) if args.robot else None
    if robot: print(f"[robot] connecting to {args.robot_host} (wheels={'on' if args.wheels else 'off'})")

    threading.Thread(target=control_loop, args=(tl, dots, radar, robot, args), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  RESONANCE ready →  http://localhost:{PORT}\n  (put the DataFeel dot on your wrist; move your hand near the radar)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if dots:
            dots.off()


if __name__ == "__main__":
    main()
