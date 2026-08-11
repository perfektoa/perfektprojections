@echo off
title winsim - TGS  (real run)
cd /d "%~dp0.."

echo ============================================================
echo   SIM TGS  -  clones your Baseline league and auto-plays it
echo ------------------------------------------------------------
echo   * Have OOTP 26 open, and NOT running as administrator
echo     (if it is, the tool can't click it - see Claude's note).
echo   * Does 1 clone the first time so you can WATCH it.
echo   * ABORT any time: slam the mouse into a screen corner.
echo   * Do not touch the mouse/keyboard once it starts clicking.
echo   Once it works, edit this file's  --runs 1  to make several.
echo ============================================================
echo.
pause
python "ootp\winsim.py" --league TGS --runs 1
echo.
echo ============================================================
echo   Done. Next: "Import TGS sims to Excel.bat"
echo ============================================================
pause
