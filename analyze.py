"""
Pre-analyze a music video once, so playback can be driven cheaply and in perfect
sync with the audio. Produces media/<name>.timeline.json:

  grid_hz : samples per second of the warmth/energy arrays
  warmth  : [-1..1] per step  (fiery/bright scenes -> +1)
  energy  : [0..1]  per step  (visual motion / intensity)
  beats   : [t_seconds, ...]  strong audio beats
  bpm     : estimated tempo
  duration

Usage:  .venv/bin/python analyze.py media/fireball.mp4
"""
import json
import subprocess
import sys

import cv2
import numpy as np
from scipy.signal import find_peaks


def scene_warmth(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    h, s, v = hsv[..., 0], hsv[..., 1] / 255, hsv[..., 2] / 255
    warm = ((h < 35) | (h > 165)) * s * v                 # reds/oranges/yellows
    cool = ((h > 85) & (h < 130)) * s * v                 # blues/cyans
    dark = v < 0.12
    warm, cool = warm * ~dark, cool * ~dark
    total = warm.sum() + cool.sum() + 1e-6
    return float((warm.sum() - cool.sum()) / total)


def analyze_video(path, grid_hz=10):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(fps / grid_hz))
    warmth, energy, prev = [], [], None
    i = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, f = cap.retrieve()
            if not ok:
                break
            small = cv2.resize(f, (160, 90), interpolation=cv2.INTER_AREA)
            warmth.append(round(scene_warmth(small), 3))
            g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
            energy.append(0.0 if prev is None else float(np.abs(g - prev).mean()))
            prev = g
        i += 1
    cap.release()
    e = np.array(energy)
    e = np.clip(e / (np.percentile(e, 95) + 1e-6), 0, 1)       # normalise motion 0..1
    return warmth, [round(x, 3) for x in e], n / fps


def analyze_beats(path, sr=22050):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"],
        capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    hop = 512
    frames = len(x) // hop
    x = x[: frames * hop].reshape(frames, hop)
    # spectral-flux-ish onset envelope: rise in short-time energy
    rms = np.sqrt((x ** 2).mean(axis=1) + 1e-9)
    flux = np.diff(rms, prepend=rms[0])
    flux = np.clip(flux, 0, None)
    flux = flux / (flux.max() + 1e-9)
    fps = sr / hop
    # tempo guess from autocorrelation of the onset envelope (60-180 bpm)
    ac = np.correlate(flux - flux.mean(), flux - flux.mean(), "full")[len(flux) - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)
    bpm = round(60 * fps / (lo + int(np.argmax(ac[lo:hi]))), 1)
    min_gap = int(fps * 60 / (bpm * 1.5))                       # don't double-count
    peaks, _ = find_peaks(flux, height=0.12, distance=max(1, min_gap))
    beats = [round(p / fps, 3) for p in peaks]
    return beats, bpm


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "media/fireball.mp4"
    print(f"analyzing {path} …")
    warmth, energy, dur = analyze_video(path)
    beats, bpm = analyze_beats(path)
    out = path.rsplit(".", 1)[0] + ".timeline.json"
    json.dump({"grid_hz": 10, "warmth": warmth, "energy": energy,
               "beats": beats, "bpm": bpm, "duration": round(dur, 2)}, open(out, "w"))
    print(f"  {len(warmth)} steps, {len(beats)} beats, {bpm} bpm, {dur:.0f}s")
    print(f"  warm frac {np.mean(np.array(warmth) > 0.2):.2f}, mean energy {np.mean(energy):.2f}")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
