#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 fehlt. Bitte von https://www.python.org/downloads/ installieren und danach erneut starten."
  read -n 1 -s -r -p "Beliebige Taste zum Beenden …"
  exit 1
fi
echo "Einmalig MIT Internet ausführen. Danach den gesamten Projektordner inklusive pakete und modelle als ZIP packen."
python3 start.py --vorbereiten
echo
read -n 1 -s -r -p "Beliebige Taste zum Beenden …"
