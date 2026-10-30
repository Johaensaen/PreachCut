@echo off
cd /d "%~dp0"
echo Einmalig MIT Internet ausfuehren. Danach den Ordner (ohne .venv, arbeit, fertig) als ZIP packen.
where py >nul 2>nul && (py -3 start.py --vorbereiten) || (python start.py --vorbereiten)
pause
