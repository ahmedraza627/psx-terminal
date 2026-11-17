@echo off
title PSX QUANT DESK - FULL AUTOPILOT
cd /d "D:\psx-smc\project-1"

echo =======================================================
echo   PSX INSTITUTIONAL TERMINAL - DAILY AUTOPILOT SYNC
echo =======================================================
echo.

echo [1/4] Auto-downloading latest PSX tape from DPS server...
python backend\scripts\auto_fetch_tape.py
echo.

echo [2/4] Syncing 1-Year NCCPL Flow and DFX Open Interest...
python backend\scripts\bootstrap_nccpl_1y.py
python backend\scripts\sync_nccpl_flow.py
python backend\scripts\sync_futures_oi.py
echo.

echo [3/4] Running Multi-Factor Engine on 1-Year Rolling Database...
python backend\scripts\process_daily_tape.py
echo.

echo [4/4] Deploying updates live to Vercel production...
git add -A
git commit -m "feat(autopilot): certified institutional 1-year flow and futures sync"
git push origin main
echo.

echo =======================================================
echo   ALL ENGINES SYNCHRONIZED AND LIVE ON VERCEL!
echo =======================================================
pause