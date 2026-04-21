@echo off
title TGS Projections
cd /d "%~dp0tgs-viz"

echo ========================================
echo   TGS Projections - Starting...
echo ========================================
echo.

:: Start the dev server (opens browser automatically)
npx vite --port 3000 --open
