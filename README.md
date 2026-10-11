# RESONANCE

Feel a music video, conduct it with your hand, and watch a robot dance to it — a multi-sensory
experience that fuses three hardware devices around one song.

A music video plays in the browser. Four things lock into a loop around it:

| Piece | What it does | Powered by |
|---|---|---|
| 🎬 **The video** | the song — beat, colour, energy | the track itself (Fireball, pre-analyzed) |
| 🔥 **DataFeel dot** | *feel the song:* warm swells through intense parts, a flash on every beat | the video's energy + your motion |
| 📡 **Infineon radar** | *conduct it:* your hand motion drives the whole show's intensity | you, contactless (60 GHz) |
| 🤖 **MasterPi robot** | *watch it perform:* sways side-to-side and rocks on every beat | the same beat map |

Move your hand near the radar and the energy meter climbs → the dot hits warmer, the robot dances
harder. Hold still and it all eases off. A live dashboard shows every device reacting in real time.

## How it works

The song is **pre-analyzed once** (`analyze.py`) into a timeline of scene warmth, visual energy, and
real audio beats. At runtime the browser plays the video with audio and reports its playback position;
a control loop reads that position, looks up the timeline, folds in your live radar motion, and drives
the dot and robot — so everything stays in sync with the music.

```
browser plays song ──▶ reports playback time
       │                       │
  pre-analyzed timeline ──▶ control loop ──▶ DataFeel dot   (warm swell + beat flash)
       ▲                       │        └──▶ MasterPi robot (sway on the beat)
  Infineon radar (your hand) ──┘        └──▶ live dashboard  (all readings, over SSE)
```

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install numpy scipy opencv-python mss pyserial yt-dlp
# plus the Infineon radar SDK wheel and the DataFeel SDK (see Hardware)

# 1. get a song and analyze it
yt-dlp -f "bv*[vcodec^=avc][height<=720]+ba" --merge-output-format mp4 -o media/fireball.mp4 "<youtube-url>"
python analyze.py media/fireball.mp4        # -> media/fireball.timeline.json

# 2. run
python resonance.py                 # video + dot + radar + dashboard
python resonance.py --robot         # also connect the MasterPi
./run_resonance.sh                  # convenience launcher
```

Then open **http://localhost:8777**, click **Start**, put the dot on your wrist, and move your hand
near the radar. **STOP** halts everything (dot off, robot stopped).

## Hardware

- **DataFeel Dot** — multi-modal haptic (heat/cold/vibration/LED) over USB (Silicon Labs CP2102,
  `10c4:ea60`). Driven in the firmware's closed-loop skin-temperature mode. SDK:
  [DataFeel/devkit-samples](https://github.com/DataFeel/devkit-samples). **Needs its own power brick** —
  USB data alone can't run the heat pump. RESONANCE is warm-only (the small heat sink saturates on
  sustained cold in ~15 s), fired as short hits so the sink recovers.
- **Infineon XENSIV BGT60TR13C** — 60 GHz FMCW radar over USB. Used two ways: breathing detection
  (chest phase, isolated from clutter) and, for this project, **motion energy** as a contactless
  conductor. The SDK's macOS library is inside the Radar Development Kit installer.
- **Hiwonder MasterPi** — Raspberry Pi mecanum-wheel robot with an arm. Controlled over SSH; a small
  daemon runs Hiwonder's `common.mecanum` / `Board` API to move on the beat. **The drive motors need
  the robot's battery** — USB-C power alone browns out the Pi when the motors spin.

## Files

| File | Role |
|---|---|
| `resonance.py` | server + control loop: drives the dot & robot from the timeline + radar, serves the dashboard |
| `resonance.html` | the live 4-panel dashboard (video, energy, DataFeel, radar, robot) |
| `analyze.py` | pre-analyzes a song into warmth / energy / beats |
| `thermoscene.py` | device drivers: `SceneReader`, `RadarBreath` (breathing + motion), `Dots` (DataFeel) |
| `dance_daemon.py` | on-robot dancer, streamed commands (live) |
| `robot_dance.py` | on-robot dancer, autonomous (has the beat map; survives Wi-Fi drops) |
| `doctor.py` | hardware check for the dot and radar |

## Gotchas we hit (so you don't)

- **MasterPi Wi-Fi "dropping" was a CPU problem.** A `bruno/robot_server.py` service pegged the CPU
  and camera, starving the network stack (ping worked, SSH timed out) and browning out the Pi into a
  reboot loop. Killing/disabling it fixed the connection.
- **Motors need the battery.** Spinning the drive motors on USB-C power alone resets the Pi
  (undervoltage — check `vcgencmd get_throttled`). Use a charged battery for movement.
- **Cold barely works on one dot.** The Peltier can only dump heat into a small sink; after ~15 s the
  sink saturates and cooling stalls. Lead with warm, or clamp a cold mass to the metal back.

---

*RESONANCE was built with three sponsor devices: a DataFeel dot, an Infineon radar, and a Hiwonder
MasterPi robot. The thermal + radar code grew out of an earlier project, ThermoScene.*
