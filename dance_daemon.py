#!/usr/bin/python3
# Runs ON the MasterPi. Reads one JSON command per line from stdin and dances:
#   {"master":0..1, "beat":0/1, "warmth":-1..1}
# LED + buzzer + arm on every tick (safe in place). Wheels only if WHEELS=1 (robot on the floor).
import json
import os
import sys
import time

from common.ros_robot_controller_sdk import Board

WHEELS = os.environ.get("WHEELS", "0") == "1"
board = Board()
chassis = None
if WHEELS:
    try:
        import common.mecanum as mecanum
        chassis = mecanum.MecanumChassis()
    except Exception:
        chassis = None


def safe(fn):
    try:
        fn()
    except Exception:
        pass


def rgb(r, g, b):
    safe(lambda: board.set_rgb([(1, int(r), int(g), int(b)), (2, int(r), int(g), int(b))]))


# home the arm to a relaxed mid pose
safe(lambda: board.pwm_servo_set_position(0.5, [[1, 1500], [3, 700], [4, 2300], [5, 780]]))
rgb(40, 15, 0)
sys.stdout.write("DANCE_READY wheels=%d\n" % WHEELS)
sys.stdout.flush()

flip = 0
last_wheel = 0.0
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
    w = float(c.get("warmth", 0))

    # LED: warm hue, brightness rides energy, brighter flash on the beat
    br = 0.18 + 0.7 * m + (0.3 if beat else 0.0)
    br = min(1.0, br)
    rgb(255 * br, (55 + 120 * max(0, w)) * br, 20 * br)

    if beat:
        flip ^= 1
        # arm groove: bob joints + flick the gripper, amplitude grows with energy
        amp = int(80 + 170 * m)
        p3 = 700 - amp if flip else 700 + amp
        p5 = 780 + amp if flip else 780 - amp
        grip = 1300 if flip else 1700
        safe(lambda: board.pwm_servo_set_position(0.12, [[3, p3], [5, p5], [1, grip]]))
        if chassis and m > 0.45:                                    # in-place yaw wiggle, alternates so it stays put
            yaw = (1.0 + 1.0 * m) * (1 if flip else -1)
            safe(lambda: chassis.set_velocity(0, 90, yaw))
            last_wheel = time.time()

    if chassis and last_wheel and time.time() - last_wheel > 0.18:
        safe(lambda: chassis.set_velocity(0, 0, 0))                 # stop wheels shortly after each wiggle
        last_wheel = 0.0

# shutdown: stop everything
if chassis:
    safe(lambda: chassis.set_velocity(0, 0, 0))
rgb(0, 0, 0)
