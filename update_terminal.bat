@echo off
echo ==============================================
echo   PSX TERMINAL ONE - DAILY TAPE SYNCHRONIZER
echo ==============================================

python backend\scripts\process_daily_tape.py

if %ERRORLEVEL% NEQ 0 (
    echo [FAILED] Market data process nahi ho saka.
    pause
    exit /b
)

git add -f frontend/public/data/latest.json
git commit -m "data: sync live session tape from official exchange closing file"
git push origin main

echo ==============================================
echo [COMPLETED] Live terminal update ho gaya hai!
echo ==============================================
pause