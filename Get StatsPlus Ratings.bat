@echo off
setlocal
cd /d "%~dp0"
echo.
echo  ===============================================
echo    Pull player ratings from StatsPlus  (TGS + BLM)
echo  ===============================================
echo.
echo  You need two values from your browser while logged in to
echo  statsplus.net:  sessionid  and  csrftoken
echo    F12  -^>  Application (or Storage)  -^>  Cookies  -^>  statsplus.net
echo  (One login covers both leagues - the same cookie pulls TGS and BLM.)
echo.
set /p SID=Paste your sessionid value, then press Enter:
set /p CSRF=Paste your csrftoken value, then press Enter:
set "STATSPLUS_COOKIE=sessionid=%SID%;csrftoken=%CSRF%"
echo.
echo  Working... pulling TGS, then BLM. StatsPlus builds each export on its
echo  end, so this can take a couple of minutes. Leave this window open.
echo.
echo  --- TGS (OSA ratings) ---
python "tgs-viz\ingest\refresh.py" --statsplus --league TGS --write
echo.
echo  --- TGS draft board (from your OOTP draft-pool CSV + the pull) ---
echo  (Export the pool from OOTP's Amateur Draft screen to import_export first.
echo   Skips automatically if the CSV isn't there.)
python "tgs-viz\ingest\draft.py" --league TGS --write
echo.
echo  --- BLM (scouted ratings) ---
python "tgs-viz\ingest\refresh.py" --statsplus --league BLM --slug blm --write
echo.
echo  ===============================================
echo   Done. Both TGS and BLM app data were updated from StatsPlus.
echo   Timestamped .bak backups of the old data were saved first.
echo   Reload the web app (and use the league switch) to see it.
echo  ===============================================
echo.
pause
endlocal
