#!/bin/bash
# Start JARVIS (stops any old copy first, uses the voice environment if it exists).
cd "$(dirname "$0")"
lsof -ti:8765 | xargs kill 2>/dev/null
if [ -x .venv/bin/python ]; then exec .venv/bin/python server.py; else exec python3 server.py; fi
