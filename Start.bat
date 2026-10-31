@echo off
cd /d "%~dp0"
REM Launch the app in the background so the user can keep working normally.
where py >nul 2>nul && (start "" /B py -3 start.py) || (start "" /B python start.py)
echo PreachCut started in the background.
title PreachCut
exit /b 0
