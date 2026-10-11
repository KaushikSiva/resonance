# ThermoScene: feel what you watch

The colours on screen and your breathing (read by an Infineon 60 GHz radar) drive heating and cooling on the DataFeel dots.

| Input | Effect on the DataFeel dots |
|---|---|
| Warm scene (fire, sunset, desert) | heat |
| Cool scene (snow, ocean, ice) | cold |
| Breathing out / in (radar) | a little warmer / a little cooler; the LEDs pulse with your breath |
| Hard scene cut | vibration double-click |

## Run

```bash
cd ~/thermoscene
.venv/bin/python thermoscene.py                       # whole main screen
.venv/bin/python thermoscene.py --region 100 200 1280 720   # only the YouTube player area
.venv/bin/python thermoscene.py --sim-breath          # no radar: fake 14 bpm breathing
.venv/bin/python thermoscene.py --no-dots             # preview the display without the dots
```

```bash
.venv/bin/python thermoscene.py --video clips/myclip.mp4             # play a clip inside the app (no screen permission needed)
.venv/bin/python thermoscene.py --video clips/myclip.mp4 --record clips/take1.mp4   # save scene + display for YouTube
.venv/bin/python doctor.py --test --radar                           # hardware check before you go on stage
```

`clips/test_fire_ocean_snow.mp4` is a 12 s test clip: 4 s fire, 4 s ocean, 4 s snow.

Press `q` in the ThermoScene window to quit. The dots switch off on exit. The dots use the firmware's closed-loop skin-temperature mode: scenes map to 28–38 °C targets, and each dot cuts out if skin goes above 40.5 °C or the heat sink above 48 °C. Tested on a real dot: skin stayed between 32 and 39 °C through repeated fire, ocean and snow loops, lagging the target by about 2–4 s.

## Hardware
- **DataFeel**: El Jefe controller over USB (CP2102N, 10c4:ea60). SDK in `vendor/devkit-samples` (official DataFeel repo).
- **Infineon**: XENSIV 60 GHz FMCW radar kit (e.g. BGT60TR13C) over USB. The SDK wheel was pulled from the Radar Development Kit installer. Sit 0.3–1.5 m in front of the radar, facing it. It needs about 20–30 s of sitting still before it shows **RADAR live**, so start the app before the judge sits down. Until the signal is good enough (quality ≥ 3), breathing is ignored and only the scene drives the dots.

## 3-minute demo script
1. **Hook (15 s):** "Videos give you sight and sound. We added touch, and you control it with your breath."
2. **Fire to snow (45 s):** a judge wears the dots and you play a clip that cuts from a campfire to a blizzard. They feel heat, then a click at the cut, then cold.
3. **Breath (45 s):** have them breathe slowly. The radar picks up their chest from about a metre away, with nothing worn, and the warmth and the LEDs follow their breathing on the display.
4. **Why it matters (45 s):** immersive video and VR, calm-breathing and meditation apps, accessible media (feel a scene's mood), and remote presence.
5. **Close (30 s):** three sponsor technologies, about 400 lines of Python, a new sense.

Run `doctor.py --test` 10 minutes before you go on. The dots take 1–2 s to change temperature, so leave each scene up for at least 4 s.

## Recording for YouTube
`--record take1.mp4` saves the scene with the display underneath at real-time speed.
Put the ThermoScene window in a corner and record the screen (OBS or Cmd+Shift+5). Film a second camera on the dots and your face.
