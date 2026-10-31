@echo off
cd /d "%~dp0"
where py >nul 2>nul && (start "" /B py -3 start.py) || (start "" /B python start.py)
echo Gottesdienst-Video-Cutter wurde im Hintergrund gestartet.
title Gottesdienst-Video-Cutter
exit /b 0
