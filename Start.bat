@echo off
cd /d "%~dp0"

:: Check for Python
where py >nul 2>nul && (set PYTHON=py -3) || (set PYTHON=python)

:: Create virtual environment and install dependencies if missing
if not exist ".venv" (
    echo First run: Creating virtual environment and installing packages...
    %PYTHON% -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip -q
    if exist "requirements.txt" (
        .venv\Scripts\python -m pip install -r requirements.txt -q
    ) else (
        .venv\Scripts\python -m pip install imageio-ffmpeg faster-whisper av gpt4all opencv-python-headless -q
    )
    echo Installation completed!
) else (
    .venv\Scripts\python -m pip install --upgrade pip -q
)

:: Start server and open browser
echo Starting PreachCut...
start /b .venv\Scripts\python start.py >nul 2>&1
timeout /t 2 >nul
start http://localhost:8766
echo PreachCut is running. Keep this window open or minimize it.
pause