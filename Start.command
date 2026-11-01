#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Please install it from https://www.python.org/downloads/ and try again."
  read -n 1 -s -r -p "Press any key to exit..."
  exit 1
fi
python3 start.py
echo
read -n 1 -s -r -p "Press any key to exit..."
