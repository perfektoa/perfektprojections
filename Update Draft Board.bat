@echo off
title Update Draft Board (TGS + BLM)
cd /d "%~dp0"

echo ============================================================
echo   DRAFT BOARDS  -  OOTP pool export + StatsPlus ratings
echo ------------------------------------------------------------
echo   Before running, for the league that is drafting:
echo    1. In OOTP: Amateur Draft screen -^> export the DRAFT POOL
echo       report to CSV. (BLM exports hitters and pitchers as two
echo       separate files - both are picked up automatically.)
echo    2. Make sure your ratings pull is recent
echo       ("Get StatsPlus Ratings.bat").
echo   Drafted players drop off automatically from the live
echo   StatsPlus pick list - just re-run this as picks come in.
echo   A league with no pool export is skipped harmlessly.
echo   No Excel needed.
echo ============================================================
echo.

echo  --- TGS ---
python "tgs-viz\ingest\draft.py" --league TGS --write
echo.
echo  --- BLM ---
python "tgs-viz\ingest\draft.py" --league BLM --slug blm --write

echo.
echo ============================================================
echo   Done. Reload the webapp (switch leagues to see each board).
echo ============================================================
pause
