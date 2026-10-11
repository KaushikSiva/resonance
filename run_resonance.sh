#!/bin/zsh
# RESONANCE — the music-video demo. Wear the dot, open the page, click Start, move your hand.
cd "$(dirname "$0")"
pkill -9 -f "thermoscene.py" 2>/dev/null; sleep 1
exec .venv/bin/python -u resonance.py "$@"
