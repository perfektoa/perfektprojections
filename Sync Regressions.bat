@echo off
title TGS - Sync Data Points (Regressions + Metadata)
cd /d "%~dp0"

echo ============================================================
echo   Sync Data Points  -  Regressions + Metadata  ^-^>  Sheets
echo ============================================================
echo.
echo   BEFORE running this: open 25 Regressions.xlsx and
echo   25 Metadata.xlsx in Excel, refresh/recalculate, and SAVE
echo   (for BOTH The Sheets BLM and The Sheets TGS).
echo.
echo   This copies the current regression + metadata constants
echo   into The Sheet Hitters/Pitchers "Data Points" tabs. It
echo   shows every change and asks before writing. Your next
echo   "Get StatsPlus Ratings" pull then updates the web app.
echo.
echo ============================================================
echo.

python "tgs-viz\ingest\sync_datapoints.py" --write

echo.
echo ============================================================
echo   Done. Run "Get StatsPlus Ratings.bat" to rebuild the app
echo   data, then refresh your browser.
echo ============================================================
pause
