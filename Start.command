#!/bin/bash
cd "$(dirname "$0")"

# Check for Python 3
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Please install it from https://www.python.org/downloads/ and try again."
  read -n 1 -s -r -p "Press any key to exit..."
  exit 1
fi

# Create virtual environment and install packages on first run
if [ ! -d ".venv" ]; then
  echo "First run: Creating virtual environment and installing packages (this may take a moment)..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip -q
  if [ -f "requirements.txt" ]; then
    .venv/bin/python -m pip install -r requirements.txt -q
  else
    .venv/bin/python -m pip install imageio-ffmpeg faster-whisper av gpt4all opencv-python-headless -q
  fi
  echo "Installation completed successfully!"
else
  .venv/bin/python -m pip install --upgrade pip -q
fi

# Start server in the background
echo "Starting PreachCut..."
.venv/bin/python start.py > /tmp/preachcut.log 2>&1 < /dev/null &
PID=$!

sleep 1
if ps -p "$PID" > /dev/null 2>&1; then
  echo "PreachCut is running in the background (PID: $PID)."
  echo "Opening browser..."
  sleep 1
  open "http://localhost:8766"
else
  echo "Startup failed! Here is the log output:"
  cat /tmp/preachcut.log
  read -n 1 -s -r -p "Press any key to exit..."
fi

exit 0