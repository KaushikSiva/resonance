#!/usr/bin/python3
# Runs ON the MasterPi. Reads one JSON command per line from stdin:
#   {"master":0..1, "beat":0/1, "warmth":-1..1}
# Dance = BODY MOVEMENT on the beat: sways side to side and rocks back/forth (mecanum strafe).
# No LED. Put the robot on the FLOOR. Speed grows with energy.
import json
import sys
import time

import common.mecanum as mecanum

chassis = mecanum.MecanumChassis()

# direction angles (from Hiwonder demo): 90=left, 270=right, 0=forward, 180=back.
# "side and back, each side": left, right, left, right, then a back-forward rock.
CYCLE = [90, 270, 90, 270, 180, 0]
STEP = 0.22          # how long each move pulse runs before stopping
GAP_STOP = True      # stop between beats so each beat is one clean step


def stop():
    try:
        chassis.set_velocity(0, 0, 0)
    except Exception:
        pass


stop()
sys.stdout.write("DANCE_READY move\n")
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
    m = max(0.0, min(1.0, float(c.get("master", 0))))
    beat = bool(c.get("beat"))
    now = time.time()

    if beat:
        direction = CYCLE[step % len(CYCLE)]
        step += 1
        speed = int(28 + 45 * m)                       # 28..73, grows with energy
        try:
            chassis.set_velocity(speed, direction, 0)
        except Exception:
            pass
        move_until = now + STEP
    elif GAP_STOP and move_until and now >= move_until:
        stop()                                         # finish the step, hold still until next beat
        move_until = 0.0

stop()
