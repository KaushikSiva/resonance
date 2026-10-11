#!/usr/bin/python3
# Runs ON the MasterPi. Reads one JSON command per line from stdin:
#   {"master":0..1, "beat":0/1}   or   {"stop":1}
# Dance = a gentle side-to-side STRAFE on the beat (left, right, left, right). On the FLOOR.
# master ~0 (stopped/paused) or {"stop":1} -> wheels stop immediately.
import json
import sys
import time

import common.mecanum as mecanum

chassis = mecanum.MecanumChassis()

CYCLE = [90, 270]        # 90 = strafe left, 270 = strafe right
STEP = 0.25              # how long each strafe pulse runs
MIN_MASTER = 0.12        # below this, don't move (treated as stopped)


def stop():
    try:
        chassis.set_velocity(0, 0, 0)
    except Exception:
        pass


stop()
sys.stdout.write("DANCE_READY strafe\n")
sys.stdout.flush()

step = 0
move_until = 0.0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        c = json.loads(line)
    except Exception:
        continue

    if c.get("stop"):                       # hard stop from the STOP button
        stop()
        move_until = 0.0
        continue

    m = max(0.0, min(1.0, float(c.get("master", 0))))
    beat = bool(c.get("beat"))
    now = time.time()

    if beat and m > MIN_MASTER:             # on the beat: one gentle strafe step
        speed = int(22 + 26 * m)            # gentle 22..48
        chassis_dir = CYCLE[step % len(CYCLE)]
        step += 1
        try:
            chassis.set_velocity(speed, chassis_dir, 0)
        except Exception:
            pass
        move_until = now + STEP
    elif move_until and now >= move_until:  # finish the step, then hold still
        stop()
        move_until = 0.0

stop()
