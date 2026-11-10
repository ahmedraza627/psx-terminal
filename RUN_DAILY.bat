@echo off
title PSX Terminal One - Auto Sync Engine
color 0b
echo =======================================================
echo    PSX TERMINAL ONE - DAILY SESSION SYNCHRONIZER
echo =======================================================
echo.

cd /d "D:\psx-smc\project-1"

python backend\scripts\process_daily_tape.py

if %ERRORLEVEL% NEQ 0 (
    color 0c
    echo.
    echo [ERROR] Script fail ho gayi.
    pause
    exit /b
)

echo.
echo [PUSHING] Synchronizing all 3 intelligence engines to Vercel...
git add -f frontend/public/data/latest.json frontend/public/data/history.json frontend/public/data/insiders.json frontend/app/history/page.tsx frontend/app/insiders/page.tsx backend/scripts/process_daily_tape.py
git commit -m "feat: synchronize live daily setups, historical audit ledger, and insider valuation engine"
git push origin main

color 0a
echo.
echo =======================================================
echo   [SUCCESS] Poora Terminal Institutional Level Par Sync Ho Gaya!
echo   Vercel: https://psx-terminal-one.vercel.app
echo =======================================================
pause