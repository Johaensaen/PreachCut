#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 fehlt. Bitte von https://www.python.org/downloads/ installieren und danach erneut starten."
  read -n 1 -s -r -p "Beliebige Taste zum Beenden …"
  exit 1
fi
setsid python3 start.py > /tmp/gottesdienst-video-cutter.log 2>&1 < /dev/null &
PID=$!
echo "Gottesdienst-Video-Cutter läuft im Hintergrund (PID: $PID)."
sleep 1
if ps -p "$PID" > /dev/null 2>&1; then
  echo "Die App wurde erfolgreich detached gestartet."
else
  echo "Der Start ist fehlgeschlagen. Bitte die Logdatei unter /tmp/gottesdienst-video-cutter.log prüfen."
fi
exit 0
