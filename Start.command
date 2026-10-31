#!/bin/bash
# Launch the PreachCut application in the background and keep the terminal session free.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Please install it from https://www.python.org/downloads/ and run the app again."
  read -n 1 -s -r -p "Press any key to exit …"
  exit 1
fi
setsid python3 start.py > /tmp/preachcut.log 2>&1 < /dev/null &
PID=$!
echo "PreachCut is running in the background (PID: $PID)."
sleep 1
if ps -p "$PID" > /dev/null 2>&1; then
  echo "The app started successfully in detached mode."
else
  echo "Startup failed. Please check the log at /tmp/preachcut.log."
fi
exit 0
