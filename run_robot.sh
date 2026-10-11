#!/bin/zsh
# RESONANCE — ROBOT (HW) mode.
# Switches the Mac's Wi-Fi to the robot's hotspot HW-676EB762, then runs all three:
# DataFeel dot + Infineon radar (over USB) + the MasterPi robot (over the hotspot).
#
# WARNING: joining the robot's hotspot DROPS the Mac's internet — this chat/assistant goes
# offline while you're on it. To get internet back: rejoin your normal Wi-Fi from the menu bar.
cd "$(dirname "$0")"
HOTSPOT="HW-676EB762"

pkill -9 -f "resonance.py|thermoscene.py" 2>/dev/null
lsof -ti :8777 2>/dev/null | xargs kill -9 2>/dev/null
sleep 3

echo "Joining the robot hotspot $HOTSPOT (internet will drop)…"
networksetup -setairportnetwork en0 "$HOTSPOT"
sleep 6
echo "Mac Wi-Fi: $(networksetup -getairportnetwork en0 2>/dev/null)"

# wait for the radar handle to free
for i in 1 2 3 4; do
  .venv/bin/python -c "from ifxradarsdk.fmcw import DeviceFmcw; exit(0 if DeviceFmcw.get_list() else 1)" 2>/dev/null && break
  sleep 3
done

echo "RESONANCE (robot mode): DataFeel + Infineon (USB) + MasterPi (hotspot)."
echo "The server auto-finds the robot on the hotspot. Open http://localhost:8777 and click Start."
echo "To get internet/assistant back: rejoin your normal Wi-Fi from the menu bar."
( sleep 3; open -a "Google Chrome" "http://localhost:8777" ) &
exec .venv/bin/python -u resonance.py --robot
