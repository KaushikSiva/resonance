#!/usr/bin/python3
# Runs ON the MasterPi, autonomously. Given Fireball's beat map, it dances through the
# whole song on its own — so a Wi-Fi drop doesn't stop it. Started once, in sync with playback.
#   python3 robot_dance.py <start_offset_seconds>
# Dance = body movement: sway side to side, rock back/forth, on every beat. No LED. On the FLOOR.
import json
import sys
import time

import common.mecanum as mecanum

chassis = mecanum.MecanumChassis()
tl = json.load(open("/tmp/fireball.timeline.json"))
beats, energy, grid, dur = tl["beats"], tl["energy"], tl["grid_hz"], tl["duration"]

offset = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
CYCLE = [90, 270, 90, 270, 180, 0]        # left, right, left, right, back, forward
STEP = 0.22


def stop():
    try:
        chassis.set_velocity(0, 0, 0)
    except Exception:
        pass


stop()
t0 = time.time() - offset                 # maps wall clock to song time
step = 0
for tb in beats:
    if tb < offset:
        continue
    wait = (t0 + tb) - time.time()
    if wait > 0.4:                        # if we're way behind (lag), skip ahead
        time.sleep(wait)
    elif wait < -0.5:
        continue
    k = min(len(energy) - 1, int(tb * grid))
    speed = int(28 + 45 * energy[k])      # bigger moves in the intense parts
    try:
        chassis.set_velocity(speed, CYCLE[step % len(CYCLE)], 0)
        time.sleep(STEP)
        stop()
    except Exception:
        pass
    step += 1
stop()
