@echo off
title TGS - Bank Season
cd /d "%~dp0"

echo ============================================================
echo   BANK SEASON  -  save actuals + freeze projections
echo ------------------------------------------------------------
echo   THE ORDER MATTERS at a season end:
echo    1. FIRST run "Get StatsPlus Ratings.bat"  (fresh ratings
echo       pull - ratings are PERISHABLE; the stats can always be
echo       re-fetched later, the ratings as-of-now cannot)
echo    2. THEN run this.
echo   It saves, for TGS then BLM:
echo    - The season's ACTUAL batting/pitching/fielding stats
echo      (backtest\actuals\LEAGUE\year\*.csv + meta.json marking
echo      whether the season was complete)
echo    - A dated snapshot of the CURRENT projections + ratings
echo      cache (backtest\snapshots\LEAGUE\in-game-date\)
echo   A loud warning appears if the ratings cache is stale.
echo   A league that is MID-SEASON is skipped automatically -
echo   only completed seasons are ever banked. So it is always
echo   safe to run this: whichever league is at its season end
echo   gets banked, the other is left alone.
echo ============================================================
echo.

echo  --- TGS: season actuals (MLB level) ---
python "tgs-viz\backtest\fetch_actuals.py" --league TGS --write
echo.
echo  --- TGS: projection snapshot ---
python "tgs-viz\backtest\snapshot_projections.py" --league TGS --write
echo.
echo  --- BLM: season actuals (MLB level) ---
python "tgs-viz\backtest\fetch_actuals.py" --league BLM --slug blm --write
if errorlevel 1 echo   (warning: BLM actuals failed - its API may differ; continuing)
echo.
echo  --- BLM: projection snapshot ---
python "tgs-viz\backtest\snapshot_projections.py" --league BLM --slug blm --write
if errorlevel 1 echo   (warning: BLM snapshot failed - continuing)

echo.
echo ============================================================
echo   Done. Actuals are in tgs-viz\backtest\actuals\ and the
echo   projection snapshots in tgs-viz\backtest\snapshots\.
echo   Old actuals get a timestamped .bak; snapshots never
echo   overwrite (a -2 suffix is added instead).
echo ============================================================
pause
