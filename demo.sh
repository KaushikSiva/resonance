#!/bin/zsh
# One command for the live demo: open the page, start the video, find it on screen, drive the dot.
#   ./demo.sh        start at the 0:25 lava dive
#   ./demo.sh 0      start from the beginning
cd "$(dirname "$0")"
START=${1:-25}
pgrep -f "http.server 8765" >/dev/null || (nohup python3 -m http.server 8765 >/dev/null 2>&1 &)
sleep 1
osascript -e "tell application \"Google Chrome\"
  activate
  open location \"http://localhost:8765/demo.html?play=$START\"
end tell" >/dev/null
echo "Waiting for the video to start…"
sleep 6
osascript -e 'tell application "Google Chrome" to activate' >/dev/null
exec .venv/bin/python -u thermoscene.py --auto --no-hud
