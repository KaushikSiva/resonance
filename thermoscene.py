"""
ThermoScene: feel what you watch.

  screen (YouTube scene colour)  ─┐
                                  ├─> mixer ─> DataFeel dots (heat / cold / LED / vibration)
  Infineon 60 GHz radar (breath) ─┘           + HUD window for recording

Warm scenes (fire, sunsets, deserts) heat the dots, cool scenes (snow, ocean, ice)
chill them. Your breathing, read by the radar, rides on top: each exhale adds a little
warmth, each inhale a little cool, and the LEDs pulse with your breath. Hard scene
cuts fire a vibration click.

Run:  .venv/bin/python thermoscene.py            (falls back to simulated parts if a device is missing)
      .venv/bin/python thermoscene.py --help
"""
import argparse
import math
import threading
import time
from collections import deque

import cv2
import mss
import numpy as np
from scipy.signal import butter, sosfiltfilt


# ---------------------------------------------------------------- screen scene

class SceneReader:
    """Scores the on-screen picture from -1 (icy) to +1 (fiery)."""

    def __init__(self, monitor=1, region=None):
        self.sct = mss.mss()
        if region:
            x, y, w, h = region
            self.box = {"left": x, "top": y, "width": w, "height": h}
        else:
            self.box = self.sct.monitors[monitor]
        self.prev = None
        self.thumb = np.zeros((90, 160, 3), np.uint8)

    def grab(self):
        return np.ascontiguousarray(np.asarray(self.sct.grab(self.box))[:, :, :3])   # BGRA -> BGR

    def read(self):
        img = self.grab()
        self.frame = img
        small = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
        self.thumb = small
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.float32)
        h, s, v = hsv[..., 0], hsv[..., 1] / 255, hsv[..., 2] / 255

        # OpenCV hue is 0-180: reds/oranges/yellows are warm, cyans/blues are cool.
        warm = ((h < 35) | (h > 165)) * s * v
        cool = ((h > 85) & (h < 130)) * s * v
        icy = (s < 0.15) * (v > 0.85) * 0.6                       # snow, ice, white glare
        dark = v < 0.12                                           # ignore black bars
        warm, cool, icy = (a * ~dark for a in (warm, cool, icy))
        total = warm.sum() + cool.sum() + icy.sum() + 1e-6
        score = float((warm.sum() - cool.sum() - icy.sum()) / total)

        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        cut = self.prev is not None and float(np.abs(gray - self.prev).mean()) > 40
        self.prev = gray
        return score, cut


class VideoScene(SceneReader):
    """Same scoring, but from a video file played inside the app (loops at the end)."""

    def __init__(self, path):
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise SystemExit(f"can't open video {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.t0 = time.time()
        self.prev = None
        self.thumb = np.zeros((90, 160, 3), np.uint8)

    def grab(self):
        # stay in real time: skip frames if the loop runs slower than the video
        want = int((time.time() - self.t0) * self.fps)
        while self.cap.get(cv2.CAP_PROP_POS_FRAMES) < want:
            if not self.cap.grab():
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.t0 = time.time()
                break
        ok, img = self.cap.retrieve()
        if not ok:
            ok, img = self.cap.read()
        return img if ok else np.zeros((360, 640, 3), np.uint8)


# ---------------------------------------------------------------- breathing

class Breath:
    """Base: exposes .wave (-1 inhale .. +1 exhale, roughly), .bpm, .live."""
    wave, bpm, live, status = 0.0, 0.0, False, ""


class SimBreath(Breath):
    status = "SIMULATED"

    def __init__(self, bpm=14):
        self.bpm, self.t0 = bpm, time.time()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            t = time.time() - self.t0
            self.wave = math.sin(2 * math.pi * self.bpm / 60 * t)
            time.sleep(0.05)


class RadarBreath(Breath):
    """Chest motion from an Infineon XENSIV 60 GHz FMCW radar (e.g. BGT60TR13C).

    Range-FFT each frame, lock onto the strongest reflector 0.25-1.5 m away (you),
    track its phase over time = chest displacement, band-pass to breathing band.
    """
    FPS = 20.0

    def __init__(self):
        from ifxradarsdk.fmcw import DeviceFmcw
        from ifxradarsdk.fmcw.types import FmcwSequenceChirp, FmcwSimpleSequenceConfig

        self.dev = DeviceFmcw()                                   # raises if no radar
        chirp = FmcwSequenceChirp(
            start_frequency_Hz=60e9, end_frequency_Hz=61.5e9,     # 1.5 GHz -> 10 cm bins
            sample_rate_Hz=1e6, num_samples=64,
            rx_mask=1, tx_mask=1, tx_power_level=31,
            lp_cutoff_Hz=500000, hp_cutoff_Hz=80000, if_gain_dB=33)
        cfg = FmcwSimpleSequenceConfig(
            frame_repetition_time_s=1 / self.FPS, chirp_repetition_time_s=0.0005,
            num_chirps=32, tdm_mimo=False, chirp=chirp)
        self.dev.set_acquisition_sequence(self.dev.create_simple_sequence(cfg))
        self.bin_m = 3e8 / (2 * 1.5e9)
        self.phase = deque(maxlen=int(self.FPS * 20))             # 20 s window
        self.mag = None
        self.target = None
        self.sos = butter(2, [0.1, 0.7], btype="band", fs=self.FPS, output="sos")
        self.status = "RADAR warming up"
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        win = np.hanning(64)
        lo, hi = int(0.25 / self.bin_m), int(1.5 / self.bin_m)
        n = 0
        while True:
            try:
                frame = self.dev.get_next_frame(timeout_ms=1000)[0][0]   # rx0: chirps x samples
            except Exception as e:
                self.live, self.status = False, f"RADAR error: {e}"
                time.sleep(0.5)
                continue
            x = frame - frame.mean(axis=1, keepdims=True)
            prof = np.fft.fft(x * win, axis=1)[:, :32].mean(axis=0)     # complex range profile
            m = np.abs(prof)
            self.mag = m if self.mag is None else 0.95 * self.mag + 0.05 * m
            n += 1
            if self.target is None or n % int(self.FPS * 5) == 0:       # re-lock every 5 s
                self.target = lo + int(np.argmax(self.mag[lo:hi]))
            self.phase.append(np.angle(prof[self.target]))
            if len(self.phase) < self.FPS * 6:
                self.status = "RADAR calibrating - sit still"
                continue

            disp = np.unwrap(np.array(self.phase))
            sig = sosfiltfilt(self.sos, disp - disp.mean())
            self.wave = float(np.clip(sig[-1] / (3 * sig.std() + 1e-9), -1, 1))
            spec = np.abs(np.fft.rfft(sig * np.hanning(len(sig)), 1024))
            freqs = np.fft.rfftfreq(1024, 1 / self.FPS)
            band = (freqs > 0.1) & (freqs < 0.7)
            self.bpm = float(freqs[band][np.argmax(spec[band])] * 60)
            self.live = True
            self.status = f"RADAR live @ {self.target * self.bin_m:.1f} m"


# ---------------------------------------------------------------- DataFeel output

class Dots:
    """Pushes the mixed state to every DataFeel dot on a background thread
    (Modbus over serial is slow, so the HUD never waits on it)."""

    def __init__(self, enabled=True, max_thermal=0.8):
        self.max = max_thermal
        self.dots, self.status = [], "no dots (preview only)"
        self.state = {"thermal": 0.0, "rgb": (0, 0, 0), "click": False}
        self.lock = threading.Lock()
        if not enabled:
            return
        try:
            from datafeel.device import discover_devices
            self.dots = discover_devices(4)
        except Exception as e:
            self.status = f"DataFeel error: {e}"
        if self.dots:
            self.status = f"{len(self.dots)} DataFeel dot(s)"
            threading.Thread(target=self._run, daemon=True).start()
        elif not self.status.startswith("DataFeel error"):
            self.status = "no DataFeel dots found (preview only)"

    def update(self, thermal, rgb, click=False):
        with self.lock:
            self.state["thermal"], self.state["rgb"] = thermal, rgb
            self.state["click"] |= click

    # The dots run in the firmware's closed-loop skin-temperature mode, not raw power:
    # raw power kept climbing (43 C after two heat pulses) and saturated the heat sink.
    NEUTRAL_C, SPAN_C = 33.0, 5.0              # thermal -max..+max  ->  28..38 C
    SKIN_LIMIT_C, SINK_LIMIT_C = 40.5, 48.0    # hard cut-outs; resume below 38 / 42

    def _target(self, d, temp):
        from datafeel.device import ThermalMode
        d.registers.set_thermal_mode(ThermalMode.TEMPERATURE_TARGET)
        d.registers.set_skin_temp_target(temp)  # SDK's activate_thermal_temperature_control has a typo

    def _run(self):
        from datafeel.device import VibrationWaveforms
        sent, resting, n = {}, set(), 0
        while True:
            with self.lock:
                s = dict(self.state)
                self.state["click"] = False
            target = round(self.NEUTRAL_C + s["thermal"] / self.max * self.SPAN_C, 1)
            n += 1
            for i, d in enumerate(self.dots):
                try:
                    if n % 4 == 0:                                 # ~1 Hz safety check + HUD readout
                        skin, sink = d.registers.get_skin_temperature(), d.registers.get_sink_temperature()
                        if skin > self.SKIN_LIMIT_C or sink > self.SINK_LIMIT_C:
                            if i not in resting:
                                d.disable_all_thermal()
                            resting.add(i)
                        elif i in resting and skin < 38 and sink < 42:
                            resting.discard(i)
                            sent.pop(i, None)
                        if i == 0:
                            rest = "  RESTING (too hot)" if resting else ""
                            self.status = f"{len(self.dots)} dot(s)  skin {skin:.1f} C -> {target:.0f} C{rest}"
                    if i not in resting and abs(target - sent.get(i, -99)) >= 0.3:
                        self._target(d, target)
                        sent[i] = target
                    d.set_led(*s["rgb"])
                    if s["click"]:
                        d.play_vibration_sequence([VibrationWaveforms.DOUBLE_CLICK_P100])
                except Exception as e:
                    self.status = f"DataFeel write error: {e}"
            time.sleep(0.25)

    def off(self):
        for d in self.dots:
            try:
                d.disable_all_thermal()
                d.set_led_off()
                d.stop_vibration()
            except Exception:
                pass


# ---------------------------------------------------------------- HUD

def draw_hud(thumb, scene, breath, thermal, history, dots_status):
    W, H = 640, 360
    hud = np.full((H, W, 3), 18, np.uint8)
    hud[10:190, 10:330] = cv2.resize(thumb, (320, 180))

    # thermometer: blue (cold) .. red (hot)
    x0, y0, bw, bh = 350, 20, 270, 26
    for i in range(bw):
        t = i / (bw - 1)
        hud[y0:y0 + bh, x0 + i] = (int(255 * (1 - t)), 60, int(255 * t))
    px = x0 + int((thermal + 1) / 2 * (bw - 1))
    cv2.rectangle(hud, (px - 3, y0 - 6), (px + 3, y0 + bh + 6), (255, 255, 255), -1)
    word = "HOT" if thermal > 0.15 else "COLD" if thermal < -0.15 else "neutral"
    put = lambda s, p, sz=0.55, c=(230, 230, 230): cv2.putText(hud, s, p, cv2.FONT_HERSHEY_SIMPLEX, sz, c, 1, cv2.LINE_AA)
    put(f"DOTS: {word}  {thermal:+.2f}", (350, 80), 0.7)
    put(f"scene   {scene:+.2f}", (350, 115))
    put(f"breath  {breath.wave:+.2f}  {breath.bpm:4.1f} bpm", (350, 140))
    put(breath.status, (350, 165), 0.45, (120, 220, 120) if breath.live else (80, 180, 255))
    put(dots_status, (350, 185), 0.45, (180, 180, 180))

    # breath + thermal traces
    gx, gy, gw, gh = 10, 210, 620, 140
    cv2.rectangle(hud, (gx, gy), (gx + gw, gy + gh), (60, 60, 60), 1)
    if len(history) > 1:
        pts_b = [(gx + int(i * gw / (history.maxlen - 1)), gy + gh // 2 - int(b * gh * 0.42)) for i, (b, _) in enumerate(history)]
        pts_t = [(gx + int(i * gw / (history.maxlen - 1)), gy + gh // 2 - int(t * gh * 0.42)) for i, (_, t) in enumerate(history)]
        cv2.polylines(hud, [np.array(pts_b)], False, (255, 200, 80), 2, cv2.LINE_AA)
        cv2.polylines(hud, [np.array(pts_t)], False, (60, 120, 255), 2, cv2.LINE_AA)
    put("breath", (gx + 8, gy + 18), 0.45, (255, 200, 80))
    put("dot heat", (gx + 75, gy + 18), 0.45, (60, 120, 255))
    return hud


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--monitor", type=int, default=1, help="screen to watch (1 = main)")
    ap.add_argument("--region", type=int, nargs=4, metavar=("X", "Y", "W", "H"), help="watch only this area, e.g. the YouTube player")
    ap.add_argument("--max", type=float, default=0.8, help="max thermal intensity 0..1 (default 0.8)")
    ap.add_argument("--breath-weight", type=float, default=0.3, help="how much breathing shifts temperature")
    ap.add_argument("--sim-breath", action="store_true", help="skip the radar, use a fake 14 bpm breath")
    ap.add_argument("--no-dots", action="store_true", help="preview only, don't drive DataFeel")
    ap.add_argument("--video", help="play this video file inside the app instead of watching the screen")
    ap.add_argument("--record", metavar="OUT.mp4", help="save the window (scene + HUD) to a video for YouTube")
    args = ap.parse_args()

    scene_reader = VideoScene(args.video) if args.video else SceneReader(args.monitor, args.region)
    breath = SimBreath()
    if not args.sim_breath:
        try:
            breath = RadarBreath()
        except Exception as e:
            print(f"[radar] not available ({e}) - using simulated breathing")
    dots = Dots(not args.no_dots, args.max)
    print(f"[dataFeel] {dots.status}")

    scene_s, thermal = 0.0, 0.0
    history = deque(maxlen=200)
    writer = None
    cv2.namedWindow("ThermoScene", cv2.WINDOW_AUTOSIZE)
    try:
        while True:
            raw, cut = scene_reader.read()
            scene_s = 0.85 * scene_s + 0.15 * raw                      # smooth out flicker
            target = (1 - args.breath_weight) * scene_s + args.breath_weight * breath.wave
            thermal = float(np.clip(0.8 * thermal + 0.2 * target, -args.max, args.max))

            # LED: orange when hot, blue when cold, brightness rides the breath
            glow = 0.35 + 0.65 * (breath.wave + 1) / 2
            t = (thermal / args.max + 1) / 2
            rgb = tuple(int(c * glow) for c in (255 * t, 80 * t + 40, 255 * (1 - t)))
            dots.update(thermal, rgb, click=cut)

            history.append((breath.wave, thermal / args.max))
            hud = draw_hud(scene_reader.thumb, scene_s, breath, thermal, history, dots.status)
            if args.video or args.record:
                # big "stage" view: the scene on top, a coloured edge glowing hot/cold, HUD below
                stage = cv2.resize(scene_reader.frame, (640, 360))
                edge = (int(255 * (1 - t)), 60, int(255 * t))
                cv2.rectangle(stage, (0, 0), (639, 359), edge, int(4 + 10 * abs(thermal) / args.max))
                hud = np.vstack([stage, hud])
            if args.record:
                if writer is None:
                    writer = cv2.VideoWriter(args.record, cv2.VideoWriter_fourcc(*"mp4v"), 15, (hud.shape[1], hud.shape[0]))
                    rec_t0, rec_n = time.time(), 0
                while rec_n < (time.time() - rec_t0) * 15:             # repeat frames to keep real-time speed
                    writer.write(hud)
                    rec_n += 1
            cv2.imshow("ThermoScene", hud)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        if writer is not None:
            writer.release()
            print(f"[record] saved {args.record}")
        dots.off()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
