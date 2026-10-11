#!/bin/zsh
# RESONANCE — INTERNET mode.
# DataFeel dot + Infineon radar + the video, over USB on your normal Wi-Fi (robot OFF).
# Use this to demo/tune with internet still up. Open http://localhost:8777 and click Start.
cd "$(dirname "$0")"

pkill -9 -f "resonance.py|thermoscene.py" 2>/dev/null
lsof -ti :8777 2>/dev/null | xargs kill -9 2>/dev/null
sleep 3                                   # let the radar/dot handles release

# wait for the radar to be free (a just-killed process can hold it a few seconds)
for i in 1 2 3 4; do
  .venv/bin/python -c "from ifxradarsdk.fmcw import DeviceFmcw; exit(0 if DeviceFmcw.get_list() else 1)" 2>/dev/null && break
  sleep 3
done

echo "RESONANCE (internet mode): DataFeel + Infineon + video. Robot off."
echo "Opening http://localhost:8777 — click Start, wear the dot, move your hand."
( sleep 3; open -a "Google Chrome" "http://localhost:8777" ) &
exec .venv/bin/python -u resonance.py
