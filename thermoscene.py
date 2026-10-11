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
import os
import threading
import time
from collections import deque

import cv2
import mss
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi, sosfiltfilt


# ---------------------------------------------------------------- screen scene

class SceneReader:
    """Scores the on-screen picture from -1 (icy) to +1 (fiery)."""

    def __init__(self, monitor=1, region=None):
        self.sct = getattr(mss, "MSS", mss.mss)()
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


REGION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".region")


def pick_region(monitor=1):
    """Screenshot the screen, let the user drag a box around the video, save it in screen points."""
    with getattr(mss, "MSS", mss.mss)() as sct:
        mon = sct.monitors[monitor]
        shot = np.ascontiguousarray(np.asarray(sct.grab(mon))[:, :, :3])
    scale = shot.shape[1] / mon["width"]                          # Retina: pixels per screen point
    view = 1400 / shot.shape[1]
    small = cv2.resize(shot, None, fx=view, fy=view)
    print("Drag a box around the video, then press ENTER (c = cancel).")
    x, y, w, h = cv2.selectROI("Pick the video area", small, showCrosshair=False)
    cv2.destroyWindow("Pick the video area")
    cv2.waitKey(1)
    if w < 20 or h < 20:
        raise SystemExit("no area picked")
    k = 1 / (view * scale)
    region = [mon["left"] + round(x * k), mon["top"] + round(y * k), round(w * k), round(h * k)]
    with open(REGION_FILE, "w") as f:
        f.write(" ".join(map(str, region)))
    print(f"[region] saved {region} -> {REGION_FILE}")
    return region


def auto_region(monitor=1, seconds=4.0):
    """Find the playing video on screen: it's the biggest area whose pixels keep changing."""
    with getattr(mss, "MSS", mss.mss)() as sct:
        mon = sct.monitors[monitor]
        frames, t0 = [], time.time()
        while time.time() - t0 < seconds:
            img = np.asarray(sct.grab(mon))[:, :, :3]
            frames.append(cv2.cvtColor(cv2.resize(img, (mon["width"] // 4, mon["height"] // 4)), cv2.COLOR_BGR2GRAY).astype(np.int16))
            time.sleep(0.25)
    motion = np.zeros(frames[0].shape, np.uint8)
    for a, b in zip(frames, frames[1:]):
        motion += (np.abs(a - b) > 10).astype(np.uint8)
    mask = (motion >= max(2, len(frames) // 5)).astype(np.uint8) * 255   # changed in several frames
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = stats[i, :4] * 4
    if w * h < 0.02 * mon["width"] * mon["height"]:
        return None                                               # nothing big is moving: video not playing
    pad = int(0.03 * min(w, h))                                   # stay inside the player's edges
    return [int(v) for v in (mon["left"] + x + pad, mon["top"] + y + pad, w - 2 * pad, h - 2 * pad)]


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
    """Chest motion from an Infineon XENSIV 60 GHz FMCW radar (BGT60TR13C).

    Range-FFT each frame on all 3 RX antennas, remove the static scene (desk, laptop),
    lock onto the 0.3-1.5 m range bin with the most breathing-band motion (your chest),
    demodulate it linearly (principal axis of the I/Q cloud), band-pass to breathing.
    .quality is the breathing peak's height over the spectrum median; below ~3 it's noise.
    """
    FPS = 20.0

    def __init__(self, dev=None):
        self.bin_m = 3e8 / (2 * 1.5e9)
        self.buf = deque(maxlen=int(self.FPS * 20))               # 20 s of range profiles
        self.target, self.quality, self.n = None, 0.0, 0
        self.sos = butter(2, [0.1, 0.7], btype="band", fs=self.FPS, output="sos")
        self.status = "RADAR warming up"
        if dev == "offline":                                      # feed frames with push() yourself
            return
        from ifxradarsdk.fmcw import DeviceFmcw
        from ifxradarsdk.fmcw.types import FmcwSequenceChirp, FmcwSimpleSequenceConfig

        for attempt in range(3):                                  # first open after a previous run can fail
            try:
                self.dev = DeviceFmcw()
                break
            except Exception:
                if attempt == 2:
                    raise                                         # no radar
                time.sleep(1.5)
        import atexit
        atexit.register(self.dev._close)                          # release it so the next run opens cleanly
        chirp = FmcwSequenceChirp(
            start_frequency_Hz=60e9, end_frequency_Hz=61.5e9,     # 1.5 GHz -> 10 cm bins
            sample_rate_Hz=1e6, num_samples=64,
            rx_mask=7, tx_mask=1, tx_power_level=31,
            lp_cutoff_Hz=500000, hp_cutoff_Hz=80000, if_gain_dB=33)
        cfg = FmcwSimpleSequenceConfig(
            frame_repetition_time_s=1 / self.FPS, chirp_repetition_time_s=0.0005,
            num_chirps=32, tdm_mimo=False, chirp=chirp)
        self.dev.set_acquisition_sequence(self.dev.create_simple_sequence(cfg))
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                frame = self.dev.get_next_frame(timeout_ms=1000)[0]       # rx x chirps x samples
            except Exception as e:
                self.live, self.status = False, f"RADAR error: {e}"
                time.sleep(0.5)
                continue
            self.push(frame)

    def push(self, frame):
        x = frame - frame.mean(axis=2, keepdims=True)
        self.buf.append(np.fft.fft(x * np.hanning(x.shape[2]), axis=2)[..., :32].mean(axis=1))  # rx x bins
        self.n += 1
        if len(self.buf) < self.FPS * 8:
            self.status = "RADAR calibrating - sit still"
            return
        if self.target is None or self.n % int(self.FPS * 2) == 0:
            self._relock()

        # stream: project the newest sample on the locked axes, causal band-pass with kept state
        v = self.buf[-1][:, self.target] - self.static
        p = sum(sg * (ax[0] * v[rx].real + ax[1] * v[rx].imag)
                for rx, (ax, sg) in enumerate(zip(self.axes, self.signs)))
        y, self.zi = sosfilt(self.sos, [p], zi=self.zi)
        self.out.append(float(y[0]))
        recent = np.array(self.out)[-int(self.FPS * 10):]
        self.wave = float(np.clip(y[0] / (1.5 * recent.std() + 1e-12), -1, 1))

        if self.n % int(self.FPS) == 0 and len(self.out) >= self.FPS * 8:     # rate + quality once a second
            sig = np.array(self.out)
            spec = np.abs(np.fft.rfft((sig - sig.mean()) * np.hanning(len(sig)), 2048))
            freqs = np.fft.rfftfreq(2048, 1 / self.FPS)
            b = (freqs > 0.1) & (freqs < 0.7)
            self.bpm = float(freqs[b][np.argmax(spec[b])] * 60)
            self.quality = float(spec[b].max() / (np.median(spec[b]) + 1e-12))
            self.live = self.quality >= 3
            where = f"@ {self.target * self.bin_m:.1f} m  q{self.quality:.0f}"
            self.status = f"RADAR live {where}" if self.live else f"RADAR weak signal {where} - face it, sit still"

    def _relock(self):
        """Pick the range bin with the most breathing-band motion, and per-antenna I/Q axes."""
        prof = np.array(self.buf)
        static = prof.mean(axis=0)
        dyn = prof - static                                       # drop the desk, laptop, walls
        lo, hi = round(0.3 / self.bin_m), round(1.5 / self.bin_m) + 1
        band = sosfiltfilt(self.sos, dyn[:, :, lo:hi], axis=0)
        energy = (np.abs(band) ** 2).sum(axis=(0, 1))
        target = lo + int(np.argmax(energy))
        if self.target is not None and energy[target - lo] < 1.5 * energy[self.target - lo]:
            target = self.target                                  # only move when clearly better (no hopping)

        axes, projs = [], []
        for rx in range(dyn.shape[1]):
            iq = np.stack([dyn[:, rx, target].real, dyn[:, rx, target].imag])
            ax = np.linalg.svd(iq @ iq.T)[0][:, 0]
            if target == self.target and np.dot(ax, self.axes[rx]) < 0:
                ax = -ax                                          # SVD sign is arbitrary: stay consistent
            axes.append(ax)
            projs.append(sosfiltfilt(self.sos, ax @ iq))
        signs = [1.0] + [1.0 if np.dot(projs[0], q) >= 0 else -1.0 for q in projs[1:]]

        if target != self.target:                                 # new spot: restart the stream cleanly
            self.zi = sosfilt_zi(self.sos) * 0
            self.out = deque(maxlen=int(self.FPS * 20))
        self.target, self.static, self.axes, self.signs = target, static[:, target], axes, signs


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
    ap.add_argument("--auto", action="store_true", help="find the playing video on screen by itself (start playback first)")
    ap.add_argument("--pick", action="store_true", help="drag a box around the video on screen (remembered in .region)")
    ap.add_argument("--full-screen", action="store_true", help="ignore the saved .region and watch the whole screen")
    ap.add_argument("--max", type=float, default=0.8, help="max thermal intensity 0..1 (default 0.8)")
    ap.add_argument("--breath-weight", type=float, default=0.3, help="how much breathing shifts temperature")
    ap.add_argument("--sim-breath", action="store_true", help="skip the radar, use a fake 14 bpm breath")
    ap.add_argument("--no-dots", action="store_true", help="preview only, don't drive DataFeel")
    ap.add_argument("--video", help="play this video file inside the app instead of watching the screen")
    ap.add_argument("--no-hud", action="store_true", help="no window (it would cover the video / Stage Manager); status prints in the terminal")
    ap.add_argument("--record", metavar="OUT.mp4", help="save the window (scene + HUD) to a video for YouTube")
    args = ap.parse_args()

    if args.auto:
        print("[region] looking for the playing video…")
        args.region = auto_region(args.monitor)
        if not args.region:
            raise SystemExit("[region] no playing video found - press play, then run again (or use --pick)")
        with open(REGION_FILE, "w") as f:
            f.write(" ".join(map(str, args.region)))
        print(f"[region] found video at {args.region}")
    elif args.pick:
        args.region = pick_region(args.monitor)
    elif not args.region and not args.full_screen and not args.video and os.path.exists(REGION_FILE):
        args.region = [int(v) for v in open(REGION_FILE).read().split()]
        print(f"[region] watching saved area {args.region} (--pick to change, --full-screen to ignore)")
    elif not args.region and not args.video:
        print("[region] watching the WHOLE screen - wallpaper and windows count too. Use --pick to watch just the video.")
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
    if not args.no_hud:
        cv2.namedWindow("ThermoScene", cv2.WINDOW_AUTOSIZE)
    last_print = 0.0
    try:
        while True:
            raw, cut = scene_reader.read()
            scene_s = 0.85 * scene_s + 0.15 * raw                      # smooth out flicker
            bw = args.breath_weight if (breath.live or isinstance(breath, SimBreath)) else 0.0   # ignore a noisy radar
            target = (1 - bw) * scene_s + bw * breath.wave
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
            if args.no_hud:
                if time.time() - last_print > 1:
                    last_print = time.time()
                    word = "HOT " if thermal > 0.15 else "COLD" if thermal < -0.15 else "--  "
                    print(f"[{word}] scene {scene_s:+.2f}  breath {breath.bpm:4.1f} bpm  | {dots.status} | {breath.status}", flush=True)
            else:
                cv2.imshow("ThermoScene", hud)
            if not args.no_hud and cv2.waitKey(1) & 0xFF in (ord("q"), 27):
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
